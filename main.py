from flask import Flask, request, send_file
import pikepdf
from lxml import etree
import io
import json
import os

app = Flask(__name__)

API_SECRET = os.environ.get('API_SECRET', 'cambiar-esto')

@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok'}

@app.route('/fill-pdf', methods=['POST'])
def fill_pdf():
    auth = request.headers.get('Authorization', '')
    if auth != f'Bearer {API_SECRET}':
        return {'error': 'No autorizado'}, 401
    try:
        pdf_file = request.files.get('pdf_file')
        field_data = json.loads(request.form.get('field_data', '{}'))
        if not pdf_file:
            return {'error': 'No se envio archivo PDF'}, 400
        pdf = pikepdf.open(io.BytesIO(pdf_file.read()))
        root = pdf.Root
        if '/AcroForm' not in root or '/XFA' not in root['/AcroForm']:
            return {'error': 'El PDF no tiene formulario XFA'}, 400
        xfa = root['/AcroForm']['/XFA']
        datasets_idx = None
        for i in range(0, len(xfa), 2):
            if str(xfa[i]) == 'datasets':
                datasets_idx = i + 1
                break
        if datasets_idx is None:
            return {'error': 'No se encontro datasets en XFA'}, 400
        datasets_stream = xfa[datasets_idx]
        xml_bytes = pikepdf.Stream(pdf, datasets_stream.read_bytes()).read_bytes()
        tree = etree.fromstring(xml_bytes)
        ns = {'xfa': 'http://www.xfa.org/schema/xfa-data/1.0/'}
        data_elem = tree.find('.//xfa:data', ns)
        if data_elem is None:
            return {'error': 'No se encontro xfa:data'}, 400
        filled = 0
        for field_name, value in field_data.items():
            for elem in data_elem.iter():
                local = etree.QName(elem.tag).localname if '}' in elem.tag else elem.tag
                if local == field_name:
                    elem.text = str(value)
                    filled += 1
                    break
        new_xml = etree.tostring(tree, xml_declaration=True, encoding='UTF-8')
        xfa[datasets_idx] = pdf.make_stream(new_xml)
        output = io.BytesIO()
        pdf.save(output)
        pdf.close()
        output.seek(0)
        return send_file(output, mimetype='application/pdf', as_attachment=True, download_name='filled.pdf')
    except Exception as e:
        return {'error': str(e)}, 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
