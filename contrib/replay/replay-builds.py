#!/usr/bin/python
# replays purchase orders from SRC to DST
# flake8: noqa

#from inventree.api import InvenTreeAPI
#api = InvenTreeAPI('https://stock.co2mon.nz/api/', token=srctoken)
#from inventree.purchaseorder import PurchaseOrder
#pos = PurchaseOrder.list(api)
#print(pos)

import json
import logging
import os
import os.path
import re
import sqlite3
import sys

import requests

from common import *

# This script didn't exist before this date, and no data being migrated was created after this date
# so we can use any events after this date as a signal that the timestamp needs updating.
OUR_EPOCH = "2023-06-01"

def create_bo(src_bo):
    data = {
        "creation_date": src_bo['creation_date'],
        "title": src_bo['title'].replace("&amp;", "&"),
        "destination": src_bo['destination'],
        "parent": src_bo['parent'],
        "part": src_bo['part'],
        "quantity": src_bo['quantity'],
        "target_date": src_bo['target_date'],
        "take_from": src_bo['take_from'],
    }
    if src_bo['issued_by_detail'] is not None:
        data["issued_by"] = src_bo['issued_by']
    if src_bo['responsible_detail'] is not None:
        data["responsible"] = getOwner(src_bo['responsible_detail']['owner_id'], src_bo['responsible_detail']['label'])
    response = request(requests.post, 'dev', 'build/', json=data)
    update_field_by_id('build_build', response.json()['pk'], 'creation_date', src_bo['creation_date'])
    return response.json()

def find_bo(src_bo, bo_list):
    for bo in bo_list:
        if bo['title'] == src_bo['title'].replace("&amp;", "&") and bo['part'] == src_bo['part'] and bo['quantity'] == src_bo['quantity']:
            return bo
    return None

def find_stockitem(src_si, si_list):
    for si in si_list:
        if si['part'] == src_si['part'] and si['supplier_part'] == src_si['supplier_part'] and not si['build'] and not si['purchase_order'] \
             and si['purchase_price'][:6] == src_si['purchase_price'][:6]:
            return si
    return None

def find_buildstock(build, si_list):
    rv = list()
    for si in si_list:
        if si['build'] == build:
            rv.append(si)
    return rv

def find_stockitem_in(part, parent, si_list):
    for si in si_list:
        if si['part'] == part and si['belongs_to'] == parent:
            return si
    return None

def partIs(part, want):
    while part != None:
        if part == want:
            return True
        part = parts[part]['variant_of']
    return False

def find_stockitem_part_po(part, po, si_list):
    for si in si_list:
        if si['consumed_by']:
            continue
        if partIs(si['part'], part) and si['purchase_order'] == po:
            return si
    return None

def find_stockitem_part_po_serial(part, po, serial, si_list):
    if serial == "DK1":
        serial = "DK0"
    elif serial == "KPA":
        serial = "KPA0"
    elif serial == "KPB":
        serial = "KPB0"
    for si in si_list:
        if partIs(si['part'], part) and si['purchase_order'] == po:
            if si['serial'] == serial or si['serial'].replace("-", "") == serial:
                return si
    return None

def createManualStock():
    for t in src_stock.values():
        if t['purchase_order'] or t['build']:
            continue
        print(f'Stock item #{t["pk"]} is not linked to a PO or BO')
        # Find original quantity
        item_tracking = get('src', f'stock/track/?item={t["pk"]}')
        for q in item_tracking.json():
            if q['tracking_type'] != 1:
                continue
            if q['deltas']['status'] == 10:
                dsi = find_stockitem(t, getDict('dev', 'stock/').values())
                if dsi:
                    print(f'Stock item #{t["pk"]} is already in dev as #{dsi["pk"]}')
                else:
                    print(f'Stock item #{t["pk"]} has a received quantity of {q["deltas"]["quantity"]} on {q["date"]}')
                    data = {
                        "part": t['part'],
                        "supplier_part": t['supplier_part'],
                        "quantity": q["deltas"]["quantity"],
                        "purchase_price": t['purchase_price'],
                        "purchase_price_currency": t['purchase_price_currency'],
                        "updated": q['date'],
                        "location": t['location'],
                    }
                    response = request(requests.post, 'dev', 'stock/', json=data)
                    dsi = response.json()
                update_field('stock_stockitem', 'id', dsi['pk'], 'updated', q['date'])
                update_field('stock_stockitemtracking', 'item_id', dsi['pk'], 'date', q['date'])
                break

def getBom(part):
    response = get('dev', f'bom/?part={part}')
    return response.json()

def findBI(part, bi_list):
    for bi in bi_list:
        if partIs(bi['part'], part):
            return bi
    return None

def findBS(part, bs_list):
    for bs in bs_list:
        if partIs(bs['part'], part):
            return bs
    return None

def findSIviaST(build, part, st_list):
    rv = dict()
    if part == 15:  # WS2812B
        # LEDs in build 13 were misallocated somehow.
        if build == 13:
            return {
                -1: ({'purchase_order': 13}, 8),
                -2: ({'purchase_order': 27}, 25)
                }
    elif part == 20:  # SSD
        # We have some missing data for SSD in the original DB, so fake up our best guess...
        # This is because these were built before our interim tracking solution landed.
        if build == 1:
            return {
                -1: ({'purchase_order': 9}, -1)
            }
        elif build == 13:
            rv[-1] = ({'purchase_order': 8}, 5)
    # And some missing data for the BoMs which we are fixing on replay
    # no ST in src, because the bom items were missing!
    elif part == 28:
        return {-1: ({'purchase_order': 15}, -1)}
    elif part == 34:   # Cases
        if build == 9:
            return {-1: ({'purchase_order': 19}, -1)}  # tentative, guessed...
        elif build == 10:
            return {
                37: (src_stock[37], 1),  # 10mm, tentative, guessed...
                38: (src_stock[38], 1),  # 15mm, tentative, guessed...
                39: (src_stock[39], 2),  # proto, tentative, guessed...
                58: (src_stock[58], 2),  # black, tentative, guessed...
                }
        elif build == 11:
            return {-1: ({'part': 55, 'purchase_order': 25}, -1)}  # co2mon.nz white cases
        elif build == 12:
            return {
                -1: ({'part': 56, 'purchase_order': 25}, 1),  # co2mon.nz black case
                -2: ({'part': 55, 'purchase_order': 25}, 2),  # co2mon.nz white cases
                -3: ({'part': 55, 'purchase_order': 31}, 5),  # co2mon.nz white cases
            }
        elif build == 14:
            return {-1: ({'part': 55, 'purchase_order': 31}, -1)}  # co2mon.nz white cases
    elif part == 41:  # Prototype covers
        if build in (7,8):
            return {-1: ({'purchase_order': 21}, -1)}
    elif part == 40:  # Covers
        if build == 10:
            return {-1: ({'purchase_order': 21}, -1)}  # Prototype covers, not sure if this is 100% correct.
        elif build in (11, 12, 14):
            return {-1: ({'purchase_order': 20}, -1)}  # fiasco 8mm covers
    # And other parts which we turned into variants, so it can't find them easily
    elif part == 69: # Case Screw
        # Need to be specific about which build used which PO :(
        if build == 9:
            return {
                -1: ({'part': 31, 'purchase_order': 17}, -1),  # Part 31, now variant of part 69
            }
        elif build == 10:
            return {
                -1: ({'part': 31, 'purchase_order': 18}, 16),  # Part 31, now variant of part 69
                -2: ({'part': 32, 'purchase_order': 18}, 4),
                -3: ({'part': 31, 'purchase_order': 17}, 4),  # Part 31, now variant of part 69
            }
        elif build == 11:
            return {
                -1: ({'part': 32, 'purchase_order': 18}, 44),  # Part 32, now variant of part 69
            }
        elif build == 12:
            return {
                -1: ({'part': 32, 'purchase_order': 17}, 20),  # Part 32, now variant of part 69
                -2: ({'part': 32, 'purchase_order': 18}, 12),  # Part 32, now variant of part 69
            }
        elif build == 14:
            return {
                -1: ({'part': 32, 'purchase_order': 33}, 12),  # Part 32, now variant of part 69
            }
    elif part == 70: # Case-Spacer
        if build in (7,8,9):
            return {-1: ({'part': 10, 'purchase_order': 1}, -1)}  # Part 10 (black spacer) was used to construct 10mm spacer.
        if build == 9:
            # 15mm spacers were cut down to 10mm
            return { -1: ({'part': 10, 'purchase_order': 1}, -1)}  # Part 10 (black spacer), now variant of part 67 & 70
        elif build == 10:
            return {
                # Actually needed 4x10mm spacers, but were cut-down from
                -1: ({'part': 66, 'purchase_order': 14}, 8),  # Part 66 (white spacer), now variant of part 67 & 70
                -2: ({'part': 10, 'purchase_order': 1}, 16),  # Part 10 (black spacer), now variant of part 67 & 70
                # 10mm spacer was needed, but was cutdown from 15mm black spacer above
                #-3: ({'part': 11, 'purchase_order': 3}, 4),  # Part 11 (10mm spacer), now variant of part 67 & 70
            }
        elif build in (11,14):
            return {55: ({'part': 66, 'purchase_order': 14}, -1)}  # Part 66 (white spacer), now variant of part 67, variant of 70.
        elif build in (12,):
            return {
                -1: ({'part': 10, 'purchase_order': 1}, 4),    # Part 10 (black spacer), now variant of part 67 & 70
                -2: ({'part': 66, 'purchase_order': 14}, 28),  # Part 66 (white spacer), now variant of part 67 & 70
            }

    for st in st_list:
        if 'buildorder' in st['deltas'] and st['deltas']['buildorder'] == build:
            si = src_stock[st['item']]
            if si['part'] == part:
                rv[si['pk']] = (si, st['deltas']['removed'])

    # BoM for part 59 had bad quantity for M3x30 (part 32), so let logic override the quantity
    # rather than what was used in src.
    if build == 9 and part == 32:
        for k, v in rv.items():
            rv[k] = (v[0], -1)

    return rv


def allocateStock(build, dst):
    aP = getDict('dev', f'build/item/?build={dst["pk"]}')
    bS = getDict('dev', f'stock/?build={dst["pk"]}')
    items = list()
    ids = list()
    for bI in getBom(dst['part']):
        if parts[bI['sub_part']]['trackable']:
            continue
        # Look for assigned stock
        bi = findBI(bI['sub_part'], aP.values())
        si = findBS(bI['sub_part'], bS.values())
        if bi:
            logging.info(f' - {bI["sub_part"]} x {bi["quantity"]} is assigned via bi #{bi["pk"]}')
            continue
        elif si:
        #if si:
            logging.info(f' - {bI["sub_part"]} x {si["quantity"]} used via si #{si["pk"]}')
            ids.append(si["pk"])
            continue
        else:
            logging.info(f' - needs part {bI["sub_part"]} x {bI["quantity"]} x {dst["quantity"]}')
            oSi = findSIviaST(build, bI['sub_part'], sT.values())
            if len(oSi) == 0:
                logging.critical(f' ! ERROR - could not find tracking entry for part {bI["sub_part"]} in build #{build}')
                sys.exit(1)
            found = 0
            for oSiPK, v in oSi.items():
                q = v[1]
                if q == -1:
                    q = bI['quantity'] * dst['quantity']
                ptype = bI['sub_part']
                if 'part' in v[0]:
                    ptype = v[0]["part"]
                logging.info(f'   + src used stock item {oSiPK} of type {ptype} from PO#{v[0]["purchase_order"]} x {q}')
                si = find_stockitem_part_po(ptype, v[0]['purchase_order'], getDict('dev', 'stock/').values())
                if not si:
                    logging.critical(f' ! ERROR - no matching stock item!')
                    sys.exit(1)
                logging.info(f'   + using stock item #{si["pk"]}')
                ids.append(si["pk"])
                items.append({
                        'bom_item': bI['pk'],
                        'stock_item': si['pk'],
                        'quantity': q,
                    })
                found += q
            if found != bI['quantity'] * dst['quantity']:
                logging.critical(f' ! ERROR - only found {found} stock for part {bI["sub_part"]} needed {bI["quantity"]} x {dst["quantity"]}')
                sys.exit(1)
    if items:
        data = {
            'items': items,
        }
        print(data)
        response = request(requests.post, 'dev', f'build/{dst["pk"]}/allocate/', json=data)
    return ids

def createBuildOutputs(build, built_stock, dst):
    dest_stock = find_buildstock(dst["pk"], getDict('dev', 'stock/').values())
    need_serial = []
    for bs in built_stock:
        found = False
        for ds in dest_stock:
            if bs['serial'] == ds['serial']:
                found = True
                break
        if not found:
            need_serial += [bs['serial']]
    if len(need_serial)>0:
        logging.info(f' + Need to create {len(need_serial)} build outputs')
        data = {
            'auto_allocate': False,
            'batch_code': "",
            'quantity': len(need_serial),
            'serial_numbers': ",".join(need_serial),
        }
        response = request(requests.post, 'dev', f'build/{dst["pk"]}/create-output/', json=data)
        ds = getDict('dev', f'stock/?build={dst["pk"]}')
        dest_stock = ds.values()
    if len(dest_stock) != len(built_stock):
        logging.critical(f'Build #{build} has {len(built_stock)} outputs in src but {len(dest_stock)} in dev')
        sys.exit(1)
    return dict(map(lambda x: (x['serial'], x), dest_stock))


def buildOutput(build, si, dsSerials, dst):
    st = list(filter(lambda x: x['item'] == si['pk'] and x['tracking_type'] == 55, sT.values()))
    if len(st) != 1:
        logging.critical(f'Could not find creation record for {si["pk"]} on Build #{k}')
        sys.exit(1)
    st = st[0]
    logging.info(f' + BO#{build} created {si["pk"]} with serial {si["serial"]} on {st["date"]}')
    di = dsSerials[si["serial"]]
    if not di:
        logging.critical(f'No matching destination build output!')
        sys.exit(1)
    logging.info(f'   - matched to {di["pk"]} with serial {di["serial"]}')
    update_field_by_id('stock_stockitem', di['pk'], 'updated', st['date'])
    update_fieldN('stock_stockitemtracking',
                  {'item_id': di['pk'], 'tracking_type': 50, 'json_extract(deltas, "$.buildorder")': dst["pk"]},
                'date', st['date'])
    if si['is_building'] == di['is_building']:
        logging.info(f'   - with matching build state{di["is_building"]}')
        return
    if not di['is_building']:
        logging.critical(f"Don't know how to handle is_building: src={si['is_building']}, dst={di['is_building']}!")
        sys.exit(1)
    tracked_parts = dict()
    for bI in getBom(dst['part']):
        if parts[bI['sub_part']]['trackable']:
            tracked_parts[bI['sub_part']] = bI['pk']
    # Match allocations
    dst_stock = getDict('dev', 'stock/')
    aP = getDict('dev', f'build/item/?build={dst["pk"]}')
    alloc_items = list()
    for ai in list(filter(lambda x: x['item'] == si['pk'] and x['tracking_type'] == 35, sT.values())):
        aid = ai['deltas']['stockitem_detail']
        # Look for already assigned stock
        bi = findBI(aid['part'], aP.values())
        if bi:
            logging.info(f' - {aid["part"]} x {bi["quantity"]} is assigned via bi #{bi["pk"]}')
            continue
        if aid['part'] == 19:  # ESP 32
            # Fix-up which ESP is in which board, based on stocktake.
            if build == 1 and si["serial"] == "2":
                aid['serial'] = "B-1"
                aid['purchase_order'] = 9
            elif build == 4 and si["serial"] == "102":
                aid['serial'] = "I-0"
                aid['purchase_order'] = 7
            elif build == 4 and si["serial"] == "100":
                aid['serial'] = "A-1"
                aid['purchase_order'] = 4
        dsi = find_stockitem_part_po_serial(aid['part'], aid['purchase_order'], aid['serial'], dst_stock.values())
        if not dsi:
            logging.critical(f'Could not find matching allocation for {aid["part"]} with serial {aid["serial"]}')
            sys.exit(1)
        bom_item = None
        if aid['part'] in tracked_parts:
            bom_item = tracked_parts[aid['part']]
        else:
            # See if we have a variant in the bom
            if parts[aid['part']]['variant_of'] in tracked_parts:
                bom_item = tracked_parts[parts[aid['part']]['variant_of']]
        if not bom_item:
            logging.critical(f'allocated part in src {aid["part"]} dopes not appear to be tracked in dst: {tracked_parts}')
            sys.exit(1)
        data = {
            'items': [{
                'bom_item': bom_item,
                'stock_item': dsi['pk'],
                'quantity': 1,
                'output': di['pk'],
            }],
        }
        response = request(requests.post, 'dev', f'build/{dst["pk"]}/allocate/', json=data)
        logging.info(f'   - Installed {aid["part"]} with serial {aid["serial"]} into {di["pk"]}')
        alloc_items.append(dsi['pk'])
    # Complete the build output
    data = {
        'accept_incomplete_allocation': False,
        'location': dst['destination'] or 2,
        'notes': st['notes'],
        'outputs': [{'output': di['pk']}],
        'status': 10,
    }
    response = request(requests.post, 'dev', f'build/{dst["pk"]}/complete/', json=data)
    update_field_by_id('stock_stockitem', di['pk'], 'updated', st['date'])
    update_fieldN('stock_stockitemtracking',
                  {'item_id': di['pk'], 'tracking_type': 55, 'json_extract(deltas, "$.buildorder")': dst["pk"]},
                  'date', st['date'])
    update_fieldN('stock_stockitemtracking',
                  {'item_id': di['pk'], 'tracking_type': 35, 'date+': '2023-06-01'},
                   'date', st['date'])
    for t in alloc_items:
        update_field_by_id('stock_stockitem', t, 'updated', st['date'])
        update_fieldN('stock_stockitemtracking',
                      {'item_id': t, 'tracking_type': 30, 'json_extract(deltas, "$.buildorder")': dst["pk"]},
                      'date', st['date'])
    return st['date']

def processBuild(build):
    dst = find_bo(src_bos[build], getDict('dev', 'build/').values())
    if dst is None:
        logging.info(f'Build #{build} is not in dev')
        dst = create_bo(src_bos[build])
    logging.info(f'Build #{build} is #{dst["pk"]}')
    if src_bos[build]['status'] == 30:
        if dst['status'] != 30:
            data = {'remove_allocated_stock': False, 'remove_incomplete_outputs': False}
            response = request(requests.post, 'dev', f'build/{dst["pk"]}/cancel/', json=data)
            logging.info(f'  - Marked {dst["pk"]} as cancelled')
        return

    # If build has children, process them before proceeding as they may be needed for allocation
    children = filter(lambda x: x['parent'] == build, src_bos.values())
    for child in children:
        logging.info(f'Processing child build #{child["pk"]} before parent #{build}')
        processBuild(child['pk'])

    # Allocate untracked stock if we're not completed
    last_build = None
    stock_ids = list()
    if dst['completed'] < dst['quantity']:
        stock_ids = allocateStock(build, dst)
        built_stock = find_buildstock(build, src_stock.values())
        dsSerials = createBuildOutputs(build, built_stock, dst)
        for si in built_stock:
            t = buildOutput(build, si, dsSerials, dst)
            if (not last_build and t) or (t and t > last_build):
                last_build = t
    # Complete the build
    if src_bos[build]['status'] == 40 and dst['status'] != 40:
        response = request(requests.post, 'dev', f'build/{dst["pk"]}/finish/', json={})
        logging.info(f' Build #{dst["pk"]} is completed!')
        update_field_by_id('build_build', dst['pk'], 'completion_date', src_bos[build]['completion_date'])
        for t in stock_ids:
            # Update the original stock item
            update_field_by_id('stock_stockitem', t, 'updated', last_build)
            try:
                update_fieldN('stock_stockitemtracking', {'item_id': t, 'tracking_type': 42, 'date+': OUR_EPOCH}, 'date', last_build)
            except:
                # OK for this not to exist, if the item was fully consumed, only 57 will be created
                pass
        # Now find/update the child stock item that was split out.
        ids = find_ids('stock_stockitemtracking', 'deltas', f'%"buildorder": {dst["pk"]},%', 'tracking_type', 57)
        for t2 in ids:
            update_fieldN('stock_stockitemtracking', {'item_id': t2, 'tracking_type': 57, 'date+': OUR_EPOCH}, 'date', last_build)
            try:
                update_fieldN('stock_stockitemtracking', {'item_id': t2, 'tracking_type': 40, 'date+': OUR_EPOCH}, 'date', last_build)
            except:
                # OK for this not to exist, if the item was fully consumed, only 57 will be created
                pass
            update_field_by_id('stock_stockitem', t2, 'updated', last_build)
    # Before moving on, check if any of the resulting stock items have further events that need to be processed
    dst_stock = getDict('dev', 'stock/')
    for item in find_buildstock(k, src_stock.values()):
        for ai in list(filter(lambda x: x['item'] == item['pk'] and x['tracking_type'] in(36, 5), sT.values())):
            serial = item['serial']
            di = find_stockitem_part_po_serial(item['part'], None, serial, dst_stock.values())
            if ai['tracking_type'] == 36:
                # Need to detach an item from this item.
                rp = src_stock[ai['deltas']['stockitem']]
                ri = find_stockitem_in(rp['part'], di['pk'], dst_stock.values())
                if not ri:
                    continue # Already done I guess
                data = {
                    'location': 2,
                    'note': ai['notes'],
                }
                response = request(requests.post, 'dev', f'stock/{ri["pk"]}/uninstall/', json=data)
                update_field_by_id('stock_stockitem', ri['pk'], 'updated', ai['date'])
                update_fieldN('stock_stockitemtracking', {'item_id': di['pk'], 'tracking_type': 36, 'date+': OUR_EPOCH}, 'date', ai['date'])
                update_fieldN('stock_stockitemtracking', {'item_id': ri['pk'], 'tracking_type': 31, 'date+': OUR_EPOCH}, 'date', ai['date'])
                logging.info(f'  - Removed {ri["pk"]} from {di["pk"]} on {ai["date"]}: {ai["notes"]}')
            elif ai['tracking_type'] == 5:
                data = ai['deltas']
                if di['status'] == data['status']:
                    continue # Already done I guess
                # Need update the status of this build.
                response = request(requests.patch, 'dev', f'stock/{di["pk"]}/', json=data)
                update_field_by_id('stock_stockitem', di['pk'], 'updated', ai['date'])
                update_fieldN('stock_stockitemtracking', {'item_id': di['pk'], 'tracking_type': 5, 'date+': OUR_EPOCH}, 'date', ai['date'])
                logging.info(f'  - Updated {di["pk"]} status to {data} on {ai["date"]}: {ai["notes"]}')

# Builds may rely on manually created stock that wasn't input via a purchase order - boo!
logging.info("Creating manual stock items")
src_stock = cacheDict('src', 'stock/')
createManualStock()

logging.info("Caching src stock tracking info")
sT = cacheDict('src', f'stock/track/')
logging.info("Caching destination part info")
parts = getDict('dev', 'part/')
logging.info("Loading src build orders")
src_bos = cacheDict('src', 'build/')

logging.info("Processing build orders")
last_build = ""
for k in sorted(src_bos.keys()):
    processBuild(k)

# Reconcile discarded/broken builds where parts were re-used with the DB.
dst_stock = getDict('dev', 'stock/')
# 11 was removed from it's case (which got reused), and never had a screen populated, or it was stolen
note = "PCB #11 removed from case to workbench, case re-used; precise date unknown"
monitor = dst_stock[288]
if monitor['serial']  != "11":
    logging.critical(f'ERROR, stock item ID for CO2 Monitor #11 is not as expected!')
    sys.exit(1)
board = dst_stock[209]
if board['serial'] != "11":
    logging.critical(f'ERROR, stock item ID for CO2 Monitor PCB #11 is not as expected!')
    sys.exit(1)
if board['belongs_to'] == monitor["pk"]:
    # Remove the PCB from the case
    data = {
        'location': 2,
        'note': note,
    }
    response = request(requests.post, 'dev', f'stock/{board["pk"]}/uninstall/', json=data)
    logging.info(f'Removed {board["pk"]} from {monitor["pk"]}: {note}')
else:
    logging.info(f'Board {board["pk"]} appears to be already removed from {monitor["pk"]}')
# Put cover back in stock
dsT = getDict('dev', f'stock/track/')
items = list(filter(lambda x: x['deltas'].get('buildorder',0) == monitor['build'] and x['tracking_type'] == 57, dsT.values()))
did = {}
for t in items:
    if dst_stock[t['item']]['part'] != 39:  # Case, Case Cover
        #print(f'Skipping {t["item"]} because {dst_stock[t["item"]]["part"]} not case cover')
        continue
    si = dst_stock[t['item']]
    old = si["pk"]
    splits = list(filter(lambda x: x['item'] == old and x['tracking_type'] == 42, dsT.values()))
    if len(splits) == 0:
        tree_id = get_field('stock_stockitem', 'tree_id', 'id', si['pk'])
        newId = raw_exec("INSERT INTO stock_stockitem (quantity, updated, review_needed, delete_on_deplete, status, location_id, part_id, "+
                         "supplier_part_id,purchase_order_id, level, lft, rght, tree_id, link, is_building, purchase_price_currency, "+
                         "purchase_price, serial_int, barcode_data, barcode_hash, metadata, parent_id)" +
                "VALUES (1, datetime(), 0, 1, 10, 2, ?, ?, ?, 1, 1, 2, ?, '', 0, ?, ?, 0, '', '', '{}', ?)",
                ( si['part'], si['supplier_part'], si['purchase_order'], tree_id, si['purchase_price_currency'],si['purchase_price'], si['pk'])
        )
        raw_exec("INSERT INTO stock_stockitemtracking (date, item_id, user_id, tracking_type, notes, deltas) VALUES (datetime(), ?, ?, ?, ?, ?)", (
            (newId, 2, 40, note, f'{{"stockitem": {old} , "quantity": 1}}')
        ))
        update_field_by_id('stock_stockitem', si['pk'], 'quantity', 1)
        raw_exec("INSERT INTO stock_stockitemtracking (date, item_id, user_id, tracking_type, notes, deltas) VALUES (datetime(), ?, ?, ?, ?, ?)", (
            (old, 2, 42, note, f'{{"stockitem": {newId}, "removed": 1, "quantity": 1}}')
        ))
        logging.info(f' - Created new stock item {newId} for part {si["part"]}')
        did[si['part']] = True
    else:
        logging.info(f' - New stock item for part {si["part"]} appears to already exist')
        did[si['part']] = True
if list(sorted(did.keys())) != [39]:
    logging.critical(f'ERROR: Did not update cover records for #11! Only did {did}')
    sys.exit(1)
# Mark assembled monitor as destroyed and PCB as needing attention
response = request(requests.patch, 'dev', f'stock/{monitor["pk"]}/', json={"status":60})
response = request(requests.patch, 'dev', f'stock/{board["pk"]}/', json={"status":50})
