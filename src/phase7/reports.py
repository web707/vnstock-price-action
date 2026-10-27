import csv,io
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
pdfmetrics.registerFont(TTFont('QTAUnicode',str(Path(__file__).parent/'assets/DejaVuSans.ttf')))
def csv_bytes(rows):
    out=io.StringIO();keys=list(dict.fromkeys(k for row in rows for k in row));writer=csv.DictWriter(out,fieldnames=keys);writer.writeheader()
    def clean(v):return "'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v
    writer.writerows({k:clean(v) for k,v in r.items()} for r in rows);return ('\ufeff'+out.getvalue()).encode('utf-8')
def pdf_bytes(title,rows,notes):
    out=io.BytesIO();style=ParagraphStyle('body',fontName='QTAUnicode',fontSize=8,leading=12);heading=ParagraphStyle('heading',parent=style,fontSize=18,leading=24,textColor=colors.HexColor('#143b49'),spaceAfter=14)
    def p(v):return Paragraph(escape('—' if v is None else (format(v,'.6g') if isinstance(v,float) else str(v))),style)
    story=[Paragraph(escape(title),heading)]+[p(n) for n in notes]+[p('PDF làm tròn số thực đến 6 chữ số có nghĩa; CSV giữ độ chính xác dữ liệu.')]+[Spacer(1,14)];keys=list(dict.fromkeys(k for row in rows for k in row))
    if keys:
        table=Table([[p(k) for k in keys]]+[[p(row.get(k)) for k in keys] for row in rows],colWidths=[760/len(keys)]*len(keys),repeatRows=1,hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dbe9ed')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f3f6f7')]),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7)]));story.append(table)
    def footer(canvas,doc):
        canvas.setFont('QTAUnicode',8);canvas.drawString(40,22,'Đây là phân tích thuật toán, không phải lời khuyên đầu tư.');canvas.drawRightString(800,22,str(doc.page))
    SimpleDocTemplate(out,pagesize=(842,595),leftMargin=40,rightMargin=40,topMargin=35,bottomMargin=42).build(story,onFirstPage=footer,onLaterPages=footer);return out.getvalue()
