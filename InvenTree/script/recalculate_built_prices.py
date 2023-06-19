# Helper script to check/fix purchase prices calculated from build orders, as
# the original logic implemented in e257e47 had some bugs (fixed in 2a03fa8)
# hence the need to recalculate...
#
# run as python manage.py shell < scripts/recalculate_built_prices.py
from InvenTree.status_codes import StockHistoryCode, BuildStatus
from build.models import Build
from stock.models import StockItemTracking

builds = Build.objects.all()
for b in builds:
  if b.status != BuildStatus.COMPLETE:
    continue
  print(f'Checking Build {b.pk} - {b.title}')
  # Build lookup of bom quantities
  q = {}
  for i in b.untracked_bom_items:
    q[i.sub_part.pk] = (i.sub_part.pk, int(i.quantity))
    # including descendants, in case the BoM item is a template/variant part
    for i2 in i.sub_part.get_descendants(include_self=False):
      q[i2.pk] = (i.sub_part.pk, int(i.quantity))

  # Find untracked stock items which contributed to this build
  si = {}
  qs = StockItemTracking.objects.filter(tracking_type=StockHistoryCode.BUILD_CONSUMED, deltas__buildorder=b.pk)
  for i in qs.values('item__part__pk', 'item__part__name', 'item__purchase_price', 'deltas__quantity'):
    bi, biq = q[i['item__part__pk']]
    pp = i['item__purchase_price']
    iq = float(i['deltas__quantity'])
    print(f' * {iq:.0f}x {i["item__part__name"]} (for {bi}) @ {pp:.4f}')
    si.setdefault(bi, [])
    for _ in range(0,int(iq)):
      si[bi].append(float(pp))
  print()

  # Now iterate the outputs and look for tracked stock items
  for n, o in enumerate(b.build_outputs.all()):
    if o.is_building:
      continue
    orig = 0.0
    if o.purchase_price:
      orig = round(float(o.purchase_price.amount),4)
    print(f' * Output #{o.serial} from {o.batch} has original price of {orig}')
    price = 0.0
    pd = []
    for bi, pl in si.items():
      _, biq = q[bi]
      partprice = 0.0
      for nn in range(0,biq):
        pli = (biq * n) + nn
        tprice = pl[pli]
        pd.append(f'{bi}@{tprice:.4f}')
        partprice += tprice
      price += partprice
    pdstr = ', '.join(pd)
    print(f'  + NZ${price:.2f} for untracked parts ({pdstr})')
    for i in o.installed_parts.all():
      print(f'  + {i.purchase_price} for {i.part.name} with serial #{i.serial}')
      price += float(i.purchase_price.amount)
    print(f'  = ${price:.4f} expected purchase_price')
    if round(price, 4) != orig:
      o.purchase_price = price
      o.save()
      print(f'  ! FIXED!')
