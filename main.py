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
    return {'status': 'ok', 'service': 'pdf-filler', 'version': '2.0'}

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
        xml_str = xml_bytes.decode('utf-8', errors='replace')

        filled = 0
        skipped = 0

        for field_path, value in field_data.items():
            safe_value = str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

            # field_path can be:
            # 1. Full XFA path: "form1.Page1.PersonalDetails.Name.FamilyName"
            # 2. Simple name: "FamilyName" (legacy)
            
            if '.' in field_path:
                # Full path mode - navigate hierarchy to find exact element
                parts = field_path.split('.')
                leaf_name = parts[-1]
                
                # Build a regex that matches the leaf element within its parent context
                # We look for the parent chain in the XML to ensure we match the right element
                # Strategy: find the innermost parent that's unique, then find the leaf inside it
                
                success = False
                # Try matching with increasing parent context until we find a unique match
                for depth in range(1, min(len(parts), 5)):
                    parent_chain = parts[-(depth+1):-1]  # parents from innermost
                    if not parent_chain:
                        continue
                    
                    # Build a pattern: <Parent>...<LeafName/>...</Parent>
                    innermost_parent = parent_chain[0]
                    
                    # Pattern: find <Parent> ... <LeafName/> ... </Parent>
                    # Using DOTALL to match across lines
                    parent_open = r'<' + re.escape(innermost_parent) + r'[^>]*>'
                    parent_close = r'</' + re.escape(innermost_parent) + r'\s*>'
                    
                    # Find the parent block
                    parent_pattern = re.compile(
                        parent_open + r'(.*?)' + parent_close, 
                        re.DOTALL
                    )
                    
                    for m in parent_pattern.finditer(xml_str):
                        block_start = m.start()
                        block_end = m.end()
                        block_content = m.group(0)
                        
                        # Check if additional parent context matches (for deeper nesting)
                        if depth > 1:
                            # Verify grandparent context
                            context_start = max(0, block_start - 500)
                            context = xml_str[context_start:block_start]
                            grandparent = parent_chain[1] if len(parent_chain) > 1 else None
                            if grandparent and f'<{grandparent}' not in context:
                                continue
                        
                        # Now find and replace the leaf element within this block
                        # Pattern 1: Self-closing <LeafName/>
                        p1 = re.compile(r'(<' + re.escape(leaf_name) + r')(\s*/\s*>)')
                        if p1.search(block_content):
                            new_block = p1.sub(
                                r'\1>' + safe_value + '</' + leaf_name + '>', 
                                block_content, count=1
                            )
                            xml_str = xml_str[:block_start] + new_block + xml_str[block_end:]
                            filled += 1
                            success = True
                            break
                        
                        # Pattern 2: Empty tag <LeafName></LeafName>
                        p2 = re.compile(r'(<' + re.escape(leaf_name) + r'>)\s*(</' + re.escape(leaf_name) + r'\s*>)')
                        if p2.search(block_content):
                            new_block = p2.sub(r'\1' + safe_value + r'\2', block_content, count=1)
                            xml_str = xml_str[:block_start] + new_block + xml_str[block_end:]
                            filled += 1
                            success = True
                            break
                        
                        # Pattern 3: Tag with existing value
                        p3 = re.compile(r'(<' + re.escape(leaf_name) + r'>)[^<]*(</' + re.escape(leaf_name) + r'\s*>)')
                        if p3.search(block_content):
                            new_block = p3.sub(r'\1' + safe_value + r'\2', block_content, count=1)
                            xml_str = xml_str[:block_start] + new_block + xml_str[block_end:]
                            filled += 1
                            success = True
                            break
                    
                    if success:
                        break
                
                if not success:
                    # Fallback: try simple leaf name match (first occurrence)
                    p1 = re.compile(r'(<' + re.escape(leaf_name) + r')(\s*/\s*>)')
                    if p1.search(xml_str):
                        xml_str = p1.sub(r'\1>' + safe_value + '</' + leaf_name + '>', xml_str, count=1)
                        filled += 1
                    else:
                        p2 = re.compile(r'(<' + re.escape(leaf_name) + r'>)\s*(</' + re.escape(leaf_name) + r'\s*>)')
                        if p2.search(xml_str):
                            xml_str = p2.sub(r'\1' + safe_value + r'\2', xml_str, count=1)
                            filled += 1
                        else:
                            skipped += 1
            else:
                # Simple name mode (legacy compatibility)
                field_name = field_path
                p1 = re.compile(r'(<' + re.escape(field_name) + r')(\s*/\s*>)')
                if p1.search(xml_str):
                    xml_str = p1.sub(r'\1>' + safe_value + '</' + field_name + '>', xml_str, count=1)
                    filled += 1
                    continue
                p2 = re.compile(r'(<' + re.escape(field_name) + r'>)\s*(</' + re.escape(field_name) + r'\s*>)')
                if p2.search(xml_str):
                    xml_str = p2.sub(r'\1' + safe_value + r'\2', xml_str, count=1)
                    filled += 1
                    continue
                p3 = re.compile(r'(<' + re.escape(field_name) + r'>)[^<]*(</' + re.escape(field_name) + r'\s*>)')
                if p3.search(xml_str):
                    xml_str = p3.sub(r'\1' + safe_value + r'\2', xml_str, count=1)
                    filled += 1

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
