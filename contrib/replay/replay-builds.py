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


def create_bo(src_bo):
    data = {
        "creation_date": src_bo['creation_date'],
        "title": src_bo['title'],
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
        if bo['title'] == src_bo['title'] and bo['part'] == src_bo['part'] and bo['quantity'] == src_bo['quantity']:
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

def find_stockitem_part_po(part, po, si_list):
    for si in si_list:
        if si['part'] == part and si['purchase_order'] == po:
            return si
    return None

def find_stockitem_part_po_serial(part, po, serial, si_list):
    if serial == "DK1":
        serial = "DK0"
    for si in si_list:
        if si['part'] == part and si['purchase_order'] == po:
            if si['serial'] == serial or re.sub(r'-(\d+)$', r'\1', si['serial']) == serial:
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
                dsi = find_stockitem(t, dst_stock.values())
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
        if bi['part'] == part:
            return bi
    return None

def findBS(part, bs_list):
    for bs in bs_list:
        if bs['part'] == part:
            return bs
    return None

def findSIviaST(build, part, st_list):
    for st in st_list:
        if 'buildorder' in st['deltas'] and st['deltas']['buildorder'] == build:
            si = src_stock[st['item']]
            if si['part'] == part:
                return si
    return None


def allocateStock(dst):
    #aP = getDict('dev', f'build/item/?build={dst["pk"]}')
    bS = getDict('dev', f'stock/?build={dst["pk"]}')
    items = list()
    ids = list()
    for bI in getBom(dst['part']):
        if parts[bI['sub_part']]['trackable']:
            continue
        # Look for assigned stock
        #bi = findBI(bI['sub_part'], aP.values())
        si = findBS(bI['sub_part'], bS.values())
        #if bi:
        #    logging.info(f' - {bI["sub_part"]} x {bi["quantity"]} is assigned via bi #{bi["pk"]}')
        #    continue
        #elif si:
        if si:
            logging.info(f' - {bI["sub_part"]} x {si["quantity"]} used via si #{si["pk"]}')
            ids.append(si["pk"])
            continue
        else:
            logging.info(f' - needs {bI["sub_part"]} x {bI["quantity"]};')
            oSi = findSIviaST(dst['pk'], bI['sub_part'], sT.values())
            if not oSi:
                logging.critical(f' ! ERROR - could not find tracking entry for {bI["sub_part"]} in build #{dst["pk"]}')
                sys.exit(1)
            logging.info(f'   + src used stock item {oSi["pk"]} from PO#{oSi["purchase_order"]}')
            si = find_stockitem_part_po(bI['sub_part'], oSi['purchase_order'], dst_stock.values())
            if not si:
                logging.critical(f' ! ERROR - no matching stock item!')
                sys.exit(1)

            logging.info(f'   + using stock item #{si["pk"]}')
            ids.append(si["pk"])
            items.append({
                    'bom_item': bI['pk'],
                    'stock_item': si['pk'],
                    'quantity': bI['quantity'] * dst['quantity'],
                })
    if items:
        data = {
            'items': items,
        }
        response = request(requests.post, 'dev', f'build/{k}/allocate/', json=data)
    return ids

def createBuildOutputs(build, built_stock, dst):
    dest_stock = find_buildstock(dst["pk"], dst_stock.values())
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
    update_field2('stock_stockitemtracking', 'item_id', di['pk'], 'tracking_type', 50, 'date', st['date'])
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
    alloc_items = list()
    for ai in list(filter(lambda x: x['item'] == si['pk'] and x['tracking_type'] == 35, sT.values())):
        aid = ai['deltas']['stockitem_detail']
        dsi = find_stockitem_part_po_serial(aid['part'], aid['purchase_order'], aid['serial'], dst_stock.values())
        if not dsi:
            logging.critical(f'Could not find matching allocation for {aid["part"]} with serial {aid["serial"]}')
            sys.exit(1)
        data = {
            'items': [{
                'bom_item': tracked_parts[aid['part']],
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
    update_field2('stock_stockitemtracking', 'item_id', di['pk'], 'tracking_type', 55, 'date', st['date'])
    update_field2('stock_stockitemtracking', 'item_id', di['pk'], 'tracking_type', 35, 'date', st['date'])
    for t in alloc_items:
        update_field_by_id('stock_stockitem', t, 'updated', st['date'])
        update_field2('stock_stockitemtracking', 'item_id', t, 'tracking_type', 30, 'date', st['date'])
    return st['date']

# Builds may rely on manually created stock that wasn't input via a purchase order - boo!
logging.info("Creating manual stock items")
dst_stock = getDict('dev', 'stock/')
src_stock = cacheDict('src', 'stock/')

createManualStock()
logging.info("Refreshing destination stock")
dst_stock = getDict('dev', 'stock/')

logging.info("Caching src stock tracking info")
sT = cacheDict('src', f'stock/track/')
logging.info("Caching destination part info")
parts = getDict('dev', 'part/')
logging.info("Loading src build orders")
src_bos = cacheDict('src', 'build/')
logging.info("Loading dest build orders")
dst_bos = getDict('dev', 'build/')

logging.info("Processing build orders")
last_build = ""
for k in sorted(src_bos.keys()):
    dst = find_bo(src_bos[k], dst_bos.values())
    if dst is None:
        logging.info(f'Build #{k} is not in dev')
        dst = create_bo(src_bos[k])
    logging.info(f'Build #{k} is #{dst["pk"]}')
    # Allocate untracked stock if we're not completed
    stock_ids = list()
    if dst['completed'] < dst['quantity']:
        stock_ids = allocateStock(dst)
        built_stock = find_buildstock(k, src_stock.values())
        dsSerials = createBuildOutputs(k, built_stock, dst)
        for si in built_stock:
            t = buildOutput(k, si, dsSerials, dst)
            if t > last_build:
                last_build = t
                print(last_build, t)
    # Complete the build
    if src_bos[k]['status'] == 40 and dst['status'] != 40:
        response = request(requests.post, 'dev', f'build/{dst["pk"]}/finish/', json={})
        logging.info(f' Build #{dst["pk"]} is completed!')
        update_field_by_id('build_build', dst['pk'], 'completion_date', src_bos[k]['completion_date'])
        for t in stock_ids:
            # Update the original stock item
            update_field_by_id('stock_stockitem', t, 'updated', last_build)
            update_field2('stock_stockitemtracking', 'item_id', t, 'tracking_type', 42, 'date', last_build)
        # Now find/update the child stock item that was split out.
        ids = find_ids('stock_stockitemtracking', 'deltas', f'%"buildorder": {dst["pk"]},%', 'tracking_type', 57)
        for t2 in ids:
            update_field2('stock_stockitemtracking', 'item_id', t2, 'tracking_type', 57, 'date', last_build)
            update_field2('stock_stockitemtracking', 'item_id', t2, 'tracking_type', 40, 'date', last_build)
            update_field_by_id('stock_stockitem', t2, 'updated', last_build)
