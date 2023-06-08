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
import pickle
import sqlite3

import requests

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)

WHO = {
    'src': {
        'url': os.getenv('SRC_URL', ''),
        'token': os.getenv('SRC_TOKEN', ''),
    },
    'dev': {
        'url': os.getenv('DST_URL', ''),
        'token': os.getenv('DST_TOKEN', ''),
    }
}

def get(which, url, **kwargs):
    token = WHO[which]['token']
    headers = {
        'AUTHORIZATION': f'Token {token}'
    }
    requrl = os.path.join(WHO[which]['url'], url)
    response = requests.get(requrl, headers=headers, **kwargs)
    if response.status_code != 200:
        raise Exception(f"Failed to get {requrl}: {response}")
    return response

def request(method, which, url, **kwargs):
    token = WHO[which]['token']
    headers = {
        'AUTHORIZATION': f'Token {token}'
    }
    requrl = os.path.join(WHO[which]['url'], url)
    response = method(requrl, headers=headers, **kwargs)
    if response.status_code >= 300:
        try:
            data = json.loads(response.text)
        except json.decoder.JSONDecodeError:
            raise Exception(f"Failed to {method} {requrl} with no error: {response}")
        raise Exception(f"Failed to {method} {requrl}: {data}")
    return response

def getDict(which, url):
    response = get(which, url)
    rv = {}
    for t in response.json():
        rv[t['pk']] = t
    return rv

try:
    _CACHE = pickle.load(open('/tmp/replay-cache.pickle', 'rb'))
except FileNotFoundError:
    _CACHE = {}

def cacheDict(which, url):
    if (which, url) in _CACHE:
        return _CACHE[(which, url)]
    rv = getDict(which, url)
    _CACHE[(which, url)] = rv
    pickle.dump(_CACHE, open('/tmp/replay-cache.pickle', 'wb'))
    return rv

def getOwner(owner_id, label):
    for owner in owners.values():
        if owner['label'] == label and owner['owner_id'] == owner_id:
            return owner['pk']
    return None

def update_field_by_id(table, pk, field, data):
    db = sqlite3.connect(os.path.expanduser('~/database.sqlite3'))
    cur = db.cursor()
    res = cur.execute(f"UPDATE {table} SET {field} = ? WHERE id = ?", (data, pk))
    if res.rowcount != 1:
        raise Exception(f"Failed to update {table} {pk} {field} to {data}")
    cur.close()
    db.commit()

def update_field(table, w1field, w1val, field, data):
    db = sqlite3.connect(os.path.expanduser('~/database.sqlite3'))
    cur = db.cursor()
    res = cur.execute(f"UPDATE {table} SET {field} = ? WHERE {w1field} = ?", (data, w1val))
    if res.rowcount <= 0:
        raise Exception(f"Failed to update {table} {w1field}={w1val} {field} to {data}")
    cur.close()
    db.commit()

def update_field2(table, w1field, w1val, w2field, w2val, field, data):
    db = sqlite3.connect(os.path.expanduser('~/database.sqlite3'))
    cur = db.cursor()
    res = cur.execute(f"UPDATE {table} SET {field} = ? WHERE {w1field} = ? AND {w2field} = ?", (data, w1val, w2val))
    if res.rowcount <= 0:
        raise Exception(f"Failed to update {table} {w1field}={w1val} AND {w2field}={w2val} {field} to {data}")
    cur.close()
    db.commit()

def update_field_like(table, limitfield, like, field, data):
    db = sqlite3.connect(os.path.expanduser('~/database.sqlite3'))
    cur = db.cursor()
    res = cur.execute(f"UPDATE {table} SET {field} = ? WHERE {limitfield} LIKE ?", (data, like))
    if res.rowcount <= 0:
        raise Exception(f"Failed to update {table} {limitfield} like {like} {field} to {data}")
    cur.close()
    db.commit()

def find_ids(table, w1field, w1like, w2field, w2val):
    db = sqlite3.connect(os.path.expanduser('~/database.sqlite3'))
    cur = db.cursor()
    res = cur.execute(f"SELECT item_id FROM {table} WHERE {w1field} LIKE ? AND {w2field} = ?", (w1like, w2val))
    rv = map(lambda x: x[0], res.fetchall())
    cur.close()
    return rv

owners = getDict('dev', 'user/owner/')
