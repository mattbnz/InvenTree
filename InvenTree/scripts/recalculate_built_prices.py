# Helper script to check/fix purchase prices calculated from build orders, as
# the original logic implemented in e257e47 had some bugs (fixed in 2a03fa8)
# hence the need to recalculate...
#
# run as python manage.py shell < scripts/recalculate_built_prices.py
from django.db.models import Avg

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
    q[i.sub_part.pk] = i.quantity
    # including descendants, in case the BoM item is a template/variant part
    for i2 in i.sub_part.get_descendants(include_self=False):
      q[i2.pk] = i.quantity

  # Find untracked stock items which contributed to this build
  base_price = 0.0
  qs = StockItemTracking.objects.filter(tracking_type=StockHistoryCode.BUILD_CONSUMED, deltas__buildorder=b.pk)
  for i in qs.values('item__part__pk', 'item__part__name').annotate(avg_price=Avg('item__purchase_price')):
    price =  i['avg_price'] * q[i['item__part__pk']]
    print(f' + {price:.4f} for {i["item__part__name"]} x{q[i["item__part__pk"]]} ({i["avg_price"]:.4f}/each (avg))')
    base_price += float(price)
  print(f' = Sub-total for untracked parts is ${base_price:.4f}')

  # Now iterate the outputs and look for tracked stock items
  for o in b.build_outputs.all():
    if o.is_building:
      continue
    print(f' * Output #{o.serial} from {o.batch} has original price of {o.purchase_price}')
    price = base_price
    for i in o.installed_parts.all():
      print(f'  + {i.purchase_price} for {i.part.name} with serial #{i.serial}')
      price += float(i.purchase_price.amount)
    print(f'  = ${price:.4f} expected purchase_price')
    if round(price, 4) != round(float(o.purchase_price.amount),4):
      o.purchase_price = price
      o.save()
      print(f'  ! FIXED!')
