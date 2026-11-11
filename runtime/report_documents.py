"""Readable Word and PDF reports from validated, structured research data."""
from pathlib import Path
from xml.sax.saxutils import escape


def cited_text(paragraph):
    return paragraph['text']+' '+''.join(f'[{n}]' for n in paragraph['sources'])


def export_report(draft, sources, directory, created):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    _word(draft,sources,directory/'report.docx',created)
    _pdf(draft,sources,directory/'report.pdf',created)


def _word(draft,sources,path,created):
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE
    doc=Document()
    section=doc.sections[0]
    section.top_margin=section.bottom_margin=Inches(.75)
    section.left_margin=section.right_margin=Inches(.8)
    section.page_width=Inches(8.5);section.page_height=Inches(11)
    normal=doc.styles['Normal'];normal.font.name='Arial';normal.font.size=Pt(11)
    normal.paragraph_format.line_spacing=1.15
    normal.paragraph_format.space_after=Pt(8)
    for name,size in [('Title',25),('Heading 1',15),('Heading 2',12)]:
        style=doc.styles[name];style.font.name='Arial';style.font.size=Pt(size)
        style.font.color.rgb=RGBColor(0,0,0)
        style.paragraph_format.keep_with_next=True
        style.paragraph_format.space_before=Pt(14)
        style.paragraph_format.space_after=Pt(7)
    # Some Word base templates include a blue border in the Title style.
    for border in doc.styles['Title']._element.xpath('.//w:pBdr'):
        border.getparent().remove(border)
    header=section.header.paragraphs[0]
    run=header.add_run('JARVIS RESEARCH');run.font.size=Pt(8);run.font.color.rgb=RGBColor(90,100,110)
    doc.add_paragraph(draft['title'],'Title')
    meta=doc.add_paragraph('Prepared '+created+' · Sources listed at the end')
    meta.runs[0].font.size=Pt(9)
    doc.add_heading('Executive summary',level=1)
    doc.add_paragraph(cited_text(draft['summary']))
    for section_data in draft['sections']:
        doc.add_heading(section_data['heading'],level=1)
        for paragraph in section_data['paragraphs']:
            doc.add_paragraph(cited_text(paragraph))
    doc.add_heading('Limitations',level=1);doc.add_paragraph(draft['limitations'])
    doc.add_heading('Sources',level=1)
    for source in sources:
        p=doc.add_paragraph()
        p.add_run(f"[{source['id']}] {source['title']}\n").bold=True
        link=OxmlElement('w:hyperlink')
        link.set(qn('r:id'),p.part.relate_to(source['url'],RELATIONSHIP_TYPE.HYPERLINK,is_external=True))
        r=OxmlElement('w:r');properties=OxmlElement('w:rPr')
        color=OxmlElement('w:color');color.set(qn('w:val'),'174E78');properties.append(color)
        r.append(properties);t=OxmlElement('w:t');t.text=source['url'];r.append(t);link.append(r);p._p.append(link)
        p.add_run('\nAccessed '+created).font.size=Pt(9)
    footer=section.footer.paragraphs[0]
    footer.add_run('Jarvis research  |  Page ').font.size=Pt(8)
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    doc.core_properties.title=draft['title'];doc.core_properties.author='Jarvis'
    doc.save(path)


def _pdf(draft,sources,path,created):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
    font='Helvetica';bold='Helvetica-Bold'
    regular_path=Path('/System/Library/Fonts/Supplemental/Arial.ttf')
    bold_path=Path('/System/Library/Fonts/Supplemental/Arial Bold.ttf')
    if regular_path.exists() and bold_path.exists():
        if 'JarvisArial' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('JarvisArial',str(regular_path)))
            pdfmetrics.registerFont(TTFont('JarvisArialBold',str(bold_path)))
        font='JarvisArial';bold='JarvisArialBold'
    body=ParagraphStyle('Body',fontName=font,fontSize=10.5,leading=15,spaceAfter=9,alignment=TA_LEFT)
    heading=ParagraphStyle('Heading',parent=body,fontName=bold,fontSize=14,leading=18,spaceBefore=12,spaceAfter=7,keepWithNext=True)
    title=ParagraphStyle('Title',parent=body,fontName=bold,fontSize=24,leading=29,spaceAfter=13)
    small=ParagraphStyle('Small',parent=body,fontSize=8.5,leading=12,textColor=colors.HexColor('#4B5663'))
    source_style=ParagraphStyle('Source',parent=body,fontSize=9,leading=13,spaceAfter=11,splitLongWords=True)
    story=[Paragraph(escape(draft['title']),title),Paragraph('Prepared '+escape(created),small),Spacer(1,8),
           Paragraph('Executive summary',heading),Paragraph(escape(cited_text(draft['summary'])),body)]
    for section in draft['sections']:
        story.append(Paragraph(escape(section['heading']),heading))
        story.extend(Paragraph(escape(cited_text(p)),body) for p in section['paragraphs'])
    story.extend([Paragraph('Limitations',heading),Paragraph(escape(draft['limitations']),body),Paragraph('Sources',heading)])
    for source in sources:
        url=escape(source['url'],{'"':'&quot;'})
        text=f"[{source['id']}] {escape(source['title'])}<br/><link href=\"{url}\" color=\"#174E78\">{url}</link><br/>Accessed {escape(created)}"
        story.append(Paragraph(text,source_style))
    def page_decor(canvas,document):
        canvas.saveState();canvas.setFont(font,8);canvas.setFillColor(colors.HexColor('#5A6470'))
        canvas.drawString(57,letter[1]-30,'JARVIS RESEARCH')
        canvas.drawString(57,30,'Prepared '+created)
        canvas.drawRightString(letter[0]-57,30,'Page '+str(document.page))
        canvas.restoreState()
    doc=SimpleDocTemplate(str(path),pagesize=letter,rightMargin=57,leftMargin=57,topMargin=54,bottomMargin=52,
                          title=draft['title'],author='Jarvis')
    doc.build(story,onFirstPage=page_decor,onLaterPages=page_decor)
