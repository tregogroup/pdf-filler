from flask import Flask, request, send_file
import pikepdf
import io
import json
import os
import re

app = Flask(__name__)

API_SECRET = os.environ.get('API_SECRET', 'cambiar-esto')

@app.route('/', methods=['GET'])
def index():
    return {'status': 'ok', 'service': 'pdf-filler'}

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

        # Read raw XML bytes - DO NOT parse with lxml
        datasets_stream = xfa[datasets_idx]
        xml_bytes = pikepdf.Stream(pdf, datasets_stream.read_bytes()).read_bytes()
        xml_str = xml_bytes.decode('utf-8', errors='replace')

        # Fill fields by replacing empty XML tags with values
        filled = 0
        for field_name, value in field_data.items():
            safe_value = str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

            # Pattern 1: Self-closing empty tag <FieldName/>
            pattern1 = re.compile(r'(<' + re.escape(field_name) + r')(\s*/\s*>)')
            if pattern1.search(xml_str):
                xml_str = pattern1.sub(r'\1>' + safe_value + '</' + field_name + '>', xml_str, count=1)
                filled += 1
                continue

            # Pattern 2: Empty tag <FieldName></FieldName>
            pattern2 = re.compile(r'(<' + re.escape(field_name) + r'>)\s*(</\s*' + re.escape(field_name) + r'\s*>)')
            if pattern2.search(xml_str):
                xml_str = pattern2.sub(r'\1' + safe_value + r'\2', xml_str, count=1)
                filled += 1
                continue

            # Pattern 3: Tag with existing value <FieldName>old</FieldName>
            pattern3 = re.compile(r'(<' + re.escape(field_name) + r'>)[^<]*(</\s*' + re.escape(field_name) + r'\s*>)')
            if pattern3.search(xml_str):
                xml_str = pattern3.sub(r'\1' + safe_value + r'\2', xml_str, count=1)
                filled += 1

        # Write back the modified XML as raw bytes - preserves original structure
        new_xml_bytes = xml_str.encode('utf-8')
        xfa[datasets_idx] = pdf.make_stream(new_xml_bytes)

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
