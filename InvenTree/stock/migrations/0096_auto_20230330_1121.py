# Generated by Django 3.2.18 on 2023-03-30 11:21

from django.db import migrations


def update_stock_history(apps, schema_editor):
    """Data migration to fix a 'shortcoming' in the implementation of StockTracking history

    Prior to https://github.com/inventree/InvenTree/pull/4488,
    shipping items via a SalesOrder did not record the SalesOrder in the tracking history.
    This PR looks to add in SalesOrder history where it does not already exist:

    - Look for StockItems which are currently assigned to a SalesOrder
    - Check that it does *not* have any appropriate history
    - Add the appropriate history!
    """

    from InvenTree.status_codes import StockHistoryCode

    StockItem = apps.get_model('stock', 'stockitem')
    StockItemTracking = apps.get_model('stock', 'stockitemtracking')

    # Find StockItems which are marked as against a SalesOrder
    items = StockItem.objects.exclude(sales_order=None)

    n = 0

    for item in items:
        # Find newest relevant history
        history = StockItemTracking.objects.filter(
            item=item,
            tracking_type__in=[StockHistoryCode.SENT_TO_CUSTOMER, StockHistoryCode.SHIPPED_AGAINST_SALES_ORDER]
        ).order_by('-date').first()

        if not history:
            continue

        # We've already updated this one, it appears
        if history.tracking_type != StockHistoryCode.SENT_TO_CUSTOMER:
            continue

        # Update the 'deltas' of this history to include SalesOrder information
        history.deltas['salesorder'] = item.sales_order.pk

        # Change the history type
        history.tracking_type = StockHistoryCode.SHIPPED_AGAINST_SALES_ORDER

        history.save()
        n += 1

    if n > 0:
        print(f"Updated {n} StockItemTracking entries with SalesOrder data")


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0095_stocklocation_external'),
    ]

    operations = [
        migrations.RunPython(
            update_stock_history, reverse_code=migrations.RunPython.noop,
        )
    ]
