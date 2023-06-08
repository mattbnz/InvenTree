#!/usr/bin/python
# replays purchase orders from SRC to DST
# flake8: noqa

#from inventree.api import InvenTreeAPI
#api = InvenTreeAPI('https://stock.co2mon.nz/api/', token=srctoken)
#from inventree.purchaseorder import PurchaseOrder
#pos = PurchaseOrder.list(api)
#print(pos)

import json
import os
import os.path
import sqlite3

import requests

from common import *


def create_po(src_po):
    data = {
        "creation_date": src_po['creation_date'],
        "description": src_po['description'],
        "link": src_po['link'].replace("&amp;", "&"),
        "supplier": src_po['supplier'],
        "supplier_reference": src_po['supplier_reference'],
        "target_date": src_po['target_date'],
    }
    if src_po['responsible_detail'] is not None:
        data["responsible"] = getOwner(src_po['responsible_detail']['owner_id'], src_po['responsible_detail']['label'])
    response = request(requests.post, 'dev', 'order/po/', json=data)
    update_field_by_id('order_purchaseorder', response.json()['pk'], 'creation_date', src_po['creation_date'])
    return response.json()

def create_li(src_li, po_pk):
    data = {
        "order": po_pk,
        "part": src_li['part'],
        "quantity": src_li['quantity'],
        "purchase_price": src_li['purchase_price'],
        "purchase_price_currency": src_li['purchase_price_currency'],
        "destination": src_li['destination'],
        "target_date": src_li['target_date'],
    }
    response = request(requests.post, 'dev', 'order/po-line/', json=data)
    return response.json()

def create_extrali(src_li, po_pk):
    data = {
        "order": po_pk,
        "reference": src_li['reference'],
        "quantity": src_li['quantity'],
        "price": src_li['price'],
    }
    response = request(requests.post, 'dev', 'order/po-extra-line/', json=data)
    return response.json()

def find_po(src_po, po_list):
    for po in po_list:
        if po['description'] == src_po['description'] and po['supplier'] == src_po['supplier']:
            return po
    return None

def find_li(src_li, li_list):
    for li in li_list:
        if li['part'] == src_li['part'] and li['quantity'] == src_li['quantity']:
            return li
    return None

def find_extrali(src_li, li_list):
    for li in li_list:
        if li['reference'] == src_li['reference'] and li['quantity'] == src_li['quantity']:
            return li
    return None

src_pos = getDict('src', 'order/po/')
dst_pos = getDict('dev', 'order/po/')

# Only exist in stock items, so we have to replicate manually.
batch_codes = {
    1: 'DK-',
    2: 'ABT-',
    3: 'DK-2-',
    4: 'A-',
    5: 'KP1-',
    6: 'KPA-',
    7: 'I-',
    9: 'B-',
    11: 'KPB-',
    26: 'DK-3-',
    28: 'OS-',
    29: 'DK-4-',
    30: 'S-1-',
    32: 'SR-1-',
}
TRACKABLES = [21, 67, 1, 19, 14, 16, 65]  # Supplier Part #s

for k in sorted(src_pos.keys()):
    dst = find_po(src_pos[k], dst_pos.values())
    if dst is None:
        print(f'PO #{k} is not in dev')
        dst = create_po(src_pos[k])
    print(f'PO #{k} is #{dst["pk"]}')
    src_lis = getDict('src', f'order/po-line/?order={k}')
    dst_lis = getDict('dev', f'order/po-line/?order={dst["pk"]}')
    received = list()
    for li in sorted(src_lis.keys()):
        dstli = find_li(src_lis[li], dst_lis.values())
        if dstli is None:
            print(f'LI #{li} is not in dev')
            dstli = create_li(src_lis[li], dst['pk'])
        if src_lis[li]['received'] != dstli['received']:
            i = {
                'line_item': dstli['pk'],
                'supplier_part': src_lis[li]['part'],
                'quantity': src_lis[li]['received'],
                'status': 10,
                'location': src_lis[li]['destination'],
            }
            if i['supplier_part'] in TRACKABLES:
                i['batch_code'] = batch_codes[dst['pk']]
            received.append(i)
    src_lis = getDict('src', f'order/po-extra-line/?order={k}')
    dst_lis = getDict('dev', f'order/po-extra-line/?order={dst["pk"]}')
    for li in sorted(src_lis.keys()):
        dstli = find_extrali(src_lis[li], dst_lis.values())
        if dstli is None:
            print(f'Extra LI #{li} is not in dev')
            create_extrali(src_lis[li], dst['pk'])
    if dst['status_text'] == 'Pending':
        response = request(requests.post, 'dev', f'order/po/{dst["pk"]}/issue/')
        update_field_by_id('order_purchaseorder', dst['pk'], 'issue_date', src_pos[k]['issue_date'])
    if len(received) > 0:
        loc = received[0]['location']
        if loc is None:
            loc = 2
        data = {
            'items': received,
            'location': loc
        }
        response = request(requests.post, 'dev', f'order/po/{dst["pk"]}/receive/', json=data)
        update_field_by_id('order_purchaseorder', dst['pk'], 'complete_date', src_pos[k]['complete_date'])
    update_field('stock_stockitem', 'purchase_order_id', dst['pk'], 'updated', f"{src_pos[k]['complete_date']} 12:20:30.0")
    update_field_like('stock_stockitemtracking', 'deltas', f'%"purchaseorder": {dst["pk"]},%', 'date', f"{src_pos[k]['complete_date']} 12:20:30.0")
