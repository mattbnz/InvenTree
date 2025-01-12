# Generated by Django 3.0.7 on 2020-11-10 10:01

from django.db import migrations, connection
import djmoney.models.fields
import common.settings


class Migration(migrations.Migration):

    dependencies = [
        ('company', '0024_unique_name_email_constraint'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplierpricebreak',
            name='price',
            field=djmoney.models.fields.MoneyField(decimal_places=4, default_currency=common.settings.currency_code_default(), help_text='Unit price at specified quantity', max_digits=19, null=True, verbose_name='Price'),
        ),
        migrations.AddField(
            model_name='supplierpricebreak',
            name='price_currency',
            field=djmoney.models.fields.CurrencyField(choices=common.settings.currency_code_mappings(), default=common.settings.currency_code_default(), editable=False, max_length=3),
        ),
    ]
