from decimal import Decimal
def compute_totals(items, intra_state=True, gst_rate=Decimal('0.18')):
    subtotal = sum(Decimal(str(i.get('qty',1))) * Decimal(str(i.get('unit_price',0))) for i in items)
    rate = Decimal(str(items[0].get('tax_rate', float(gst_rate)))) if items else gst_rate
    if intra_state:
        cgst = (subtotal * (rate/2)).quantize(Decimal('0.01'))
        sgst = (subtotal * (rate/2)).quantize(Decimal('0.01'))
        igst = Decimal('0.00')
    else:
        cgst = sgst = Decimal('0.00')
        igst = (subtotal * rate).quantize(Decimal('0.01'))
    total = (subtotal + cgst + sgst + igst).quantize(Decimal('0.01'))
    return (subtotal.quantize(Decimal('0.01')), cgst, sgst, igst, total)
