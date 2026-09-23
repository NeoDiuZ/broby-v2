"""PDF exports from stored records. No generated clinical content."""
from io import BytesIO
from html import escape
from pathlib import Path
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from fastapi import APIRouter,Request,Response
from db import connection,get,all_records
from billing import net_total,outstanding,refund_due
from actions import owned,fail
router=APIRouter()
font=Path(__file__).parent/'assets/PlusJakartaSans-Variable.ttf'
pdfmetrics.registerFont(TTFont('Broby',str(font)))
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
styles=getSampleStyleSheet()
styles.add(ParagraphStyle('BrobyBody',fontName='Broby',fontSize=10,leading=16,spaceAfter=8))
styles.add(ParagraphStyle('BrobyHeading',fontName='Broby',fontSize=15,leading=20,spaceAfter=12,textColor=colors.HexColor('#167f73')))
def p(text,heading=False):
    value=str(text);style=styles['BrobyHeading' if heading else 'BrobyBody']
    if any(ord(ch)>0x2e80 for ch in value):style=ParagraphStyle('CJK',parent=style,fontName='STSong-Light',wordWrap='CJK')
    return Paragraph(escape(value).replace('\n','<br/>'),style)
def render(title,clinic,patient,content):
    result=BytesIO();doc=SimpleDocTemplate(result,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=42,bottomMargin=44,title=title,author=clinic['data']['name'])
    story=[p(clinic['data']['name'],True),p(title,True),p('Patient: '+patient['data']['name']+' · '+patient['data']['species']+' · ID '+patient['id']),Spacer(1,14),*content]
    def footer(canvas,document):
        canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#777777'));canvas.drawString(42,25,'Broby · Exported from stored clinic records');canvas.drawRightString(A4[0]-42,25,str(document.page))
    doc.build(story,onFirstPage=footer,onLaterPages=footer);return result.getvalue()

def discharge_document(practice,data):
    content=[p('Approved care information. Contact your clinic with questions; do not change prescribed treatment without its advice.')]
    for e in data['events']:
        content.extend([p(e['data']['title']+' · '+e['data']['occurred_at'][:10],True),p(e['data']['body'])])
        for o in e['data'].get('observations',[]):content.append(p(f"{o['name']}: {o['value']} {o['unit']} · supplied reference {o['ref_low']}–{o['ref_high']}"))
    content.append(p('Recorded medication instructions',True))
    for m in data['medications']:
        d=m['data'];content.extend([p(d['name'],True),p(d['dose']+' · '+d['frequency']),p(d['instructions'])])
    if not data['medications']:content.append(p('No medication instructions shared.'))
    content.append(p('Upcoming care',True))
    due=[r for r in data['reminders'] if r['data']['status']=='due']
    for r in due:content.append(p(r['data']['due']+' · '+r['data']['title']))
    if not due:content.append(p('No care reminders scheduled.'))
    if data['emergency_phone']:content.append(p('Clinic contact: '+data['emergency_phone']))
    return render('Care instructions',practice,data['patient'],content)
@router.get('/api/consultations/{id}/pdf')
def consultation_pdf(id:str,request:Request):
    from main import identity
    clinic,_=identity(request)
    with connection() as c:
        r=owned(c,id,clinic,'consultation');patient=owned(c,r['data']['patient_id'],clinic,'patient');practice=get(c,clinic,clinic)
        if not r['data'].get('summary'):fail('Create a document before exporting')
        content=[p('Status: '+r['data']['status']+' · Revision '+str(r['version'])+' · '+r['updated_at'][:10])]
        for s in r['data']['summary']:
            content.extend([p(s['name'],True),p(s['text'])])
            if s.get('source_ids'):content.append(p('Source receipts: '+', '.join(s['source_ids'])))
    return Response(render(r['data']['title'],practice,patient,content),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="consultation.pdf"'})
@router.get('/api/invoices/{id}/pdf')
def invoice_pdf(id:str,request:Request):
    from main import identity
    clinic,_=identity(request)
    with connection() as c:
        r=owned(c,id,clinic,'invoice');patient=owned(c,r['data']['patient_id'],clinic,'patient');practice=get(c,clinic,clinic);d=r['data']
        rows=[[p('Item'),p('Qty'),p('Unit SGD'),p('Total SGD')]]+[[p(i['name']),p(i['quantity']),p(f"{i['price_cents']/100:.2f}"),p(f"{i['quantity']*i['price_cents']/100:.2f}")] for i in d['items']]
        table=Table(rows,colWidths=[270,45,75,120],repeatRows=1,hAlign='LEFT');table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef3ed')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#deded6')),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
        content=[p('Status: '+d['status']+' · '+r['created_at'][:10]),table,Spacer(1,20),p(f"Subtotal: SGD {d.get('subtotal_cents',d['total_cents'])/100:.2f}"),p(f"Discount: SGD {d.get('discount_cents',0)/100:.2f}"),p(f"Tax ({d.get('tax_bps',0)/100:g}%): SGD {d.get('tax_cents',0)/100:.2f}"),p(f"Original total: SGD {d['total_cents']/100:.2f}",True),p(f"Credit notes less reversals: SGD {d.get('credited_cents',0)/100:.2f}"),p(f"Net invoice charge: SGD {net_total(d)/100:.2f}"),p(f"Payments less refunds recorded: SGD {d['paid_cents']/100:.2f}"),p(f"Outstanding: SGD {outstanding(d)/100:.2f}"),p(f"Refund due: SGD {refund_due(d)/100:.2f}"),p('This document does not process a payment or refund.')]
    return Response(render(d['number'],practice,patient,content),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="invoice.pdf"'})


@router.get('/api/credit-notes/export')
def credit_register(request:Request):
    import csv
    from io import StringIO
    from main import identity
    clinic,_=identity(request)
    with connection() as c:
        credits=all_records(c,clinic,'credit_note')
        reversals={r['data']['credit_note_id']:r for r in all_records(c,clinic,'credit_note_reversal')}
    output=StringIO();writer=csv.writer(output)
    writer.writerow(['Credit note','Invoice','Issued UTC','Currency','Net credit cents','Tax credit cents','Total credit cents','Reason','Status','Reversed UTC','Reversal reason','Record ID'])
    def cell(value):
        value=str(value)
        return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else value
    for r in sorted(credits,key=lambda r:(r['created_at'],r['id'])):
        d=r['data'];rev=reversals.get(r['id'])
        writer.writerow([cell(v) for v in [d['number'],d['invoice_number'],r['created_at'],'SGD',d['net_cents'],d['tax_cents'],d['amount_cents'],d['reason'],'reversed' if rev else 'issued',rev['created_at'] if rev else '',rev['data']['reason'] if rev else '',r['id']]])
    return Response(output.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="broby-credit-notes.csv"'})


@router.get('/api/credit-notes/{id}/pdf')
def credit_note_pdf(id:str,request:Request):
    from main import identity
    clinic,_=identity(request)
    with connection() as c:
        r=owned(c,id,clinic,'credit_note');d=r['data']
        reversal=next((v for v in all_records(c,clinic,'credit_note_reversal') if v['data']['credit_note_id']==id),None)
        # Issued identity and amounts are immutable, even after later patient edits.
        practice={'data':{'name':d['clinic_name']}}
        patient={'id':d['patient_id'],'data':{'name':d['patient_name'],'species':d['patient_species']}}
        content=[p('Credit note '+d['number'],True),p('Invoice: '+d['invoice_number']),p('Issued UTC: '+r['created_at']),p('Owner at issue: '+d['owner_name']),p('Reason: '+d['reason']),p(f"Credit before tax: SGD {d['net_cents']/100:.2f}"),p(f"Tax credit supplied by clinic: SGD {d['tax_cents']/100:.2f}"),p(f"Total credit: SGD {d['amount_cents']/100:.2f}",True),p('Status: '+('Reversed' if reversal else 'Issued'))]
        if reversal:content.extend([p('Reversed UTC: '+reversal['created_at']),p('Reversal reason: '+reversal['data']['reason'])])
        content.extend([p('This credit changes the invoice charge. It does not send a refund or return stock.'),p('Amounts and tax allocation were entered by clinic staff. Clinic accounting and tax policy approval is required before real-clinic use.'),p('Record ID: '+r['id'])])
    return Response(render(d['number'],practice,patient,content),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="credit-note.pdf"'})
