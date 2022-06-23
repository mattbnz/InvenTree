# Helper script to check/fix purchase prices calculated from build orders, as
# the original logic implemented in e257e47 had some bugs (fixed in 2a03fa8)
# hence the need to recalculate...
#
# run as python manage.py < scripts/recalculate_built_prices.py

from InvenTree.status_codes import StockHistoryCode
from build.models import Build
from stock.models import StockItemTracking

builds = Build.objects.all()
for b in builds:
  print(f'Checking Build {b.pk} - {b.title}')
  # Build lookup of bom quantities
  q = {}
  for i in b.untracked_bom_items:
    q[i.sub_part.pk] = i.quantity
  # Find untracked stock items which contributed to this build
  base_price = 0.0
  for i in StockItemTracking.objects.filter(tracking_type=StockHistoryCode.BUILD_CONSUMED):
    if i.deltas.get('buildorder', -1) != b.pk:
      continue
    price =  i.item.purchase_price * q[i.item.part.pk]
    print(f' + {price} for {i.item.part.name} x{q[i.item.part.pk]} ({i.item.purchase_price}/each) {i.id}')
    base_price += price
  print(f' = Sub-total for untracked parts is ${base_price}')

  # Now iterate the outputs and look for tracked stock items
  for o in b.build_outputs.all():
    if o.is_building:
      continue
    print(f' * Output #{o.serial} from {o.batch} has original price of {o.purchase_price}')
    price = base_price
    for i in o.installed_parts.all():
      print(f'  + {i.purchase_price} for {i.part.name} with serial #{i.serial}')
      price += i.purchase_price
    print(f'  = ${price} expected purchase_price')
    if price != o.purchase_price:
      o.purchase_price = price
      o.save()
      print(f'  ! FIXED!')
