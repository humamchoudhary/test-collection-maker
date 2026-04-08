#!/usr/bin/env python3
"""
Script to generate posting.yaml files from API endpoint definitions in output.txt
"""

import os
import re
from pathlib import Path

def parse_endpoints_from_file(filepath):
    """Parse the output.txt file and extract all endpoints with their details."""
    endpoints = []
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Split by file sections (each section starts with filename:line:)
    lines = content.split('\n')
    
    current_file = None
    current_endpoint = None
    current_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Check if this is a new endpoint definition (filename:line:app.method)
        match = re.match(r'^([^:]+\.js):(\d+):app\.(get|post|put|delete|patch)\(', line)
        if match:
            # Save previous endpoint if exists
            if current_endpoint and current_lines:
                current_endpoint['code_lines'] = current_lines
                endpoints.append(current_endpoint)
            
            filepath_parts = match.group(1)
            line_num = int(match.group(2))
            method = match.group(3).upper()
            
            # Extract the route path
            route_match = re.search(r'app\.\w+\([\'"]([^\'"]+)[\'"]', line)
            route_path = route_match.group(1) if route_match else ""
            
            # Determine if it requires auth
            has_auth = 'auth' in line or 'admin_auth' in line
            
            current_file = filepath_parts
            current_endpoint = {
                'file': filepath_parts,
                'line': line_num,
                'method': method,
                'path': route_path,
                'has_auth': has_auth,
                'code_lines': []
            }
            current_lines = [line]
        elif current_endpoint is not None and line.strip():
            # Check if this line belongs to the current file
            # Format can be: filename:line- or filename-line-
            if line.startswith(current_file + ':') or line.startswith(current_file + '-'):
                current_lines.append(line)
            else:
                # End of current endpoint
                current_endpoint['code_lines'] = current_lines
                endpoints.append(current_endpoint)
                current_endpoint = None
                current_lines = []
        
        i += 1
    
    # Don't forget the last endpoint
    if current_endpoint and current_lines:
        current_endpoint['code_lines'] = current_lines
        endpoints.append(current_endpoint)
    
    return endpoints


def extract_request_body_params(code_lines):
    """Extract request body parameters from the code."""
    params = {}
    code_text = '\n'.join(code_lines)
    
    # First, clean up the code text by removing line prefixes like "bins/add.js-30-"
    # This handles multi-line destructuring patterns
    cleaned_text = re.sub(r'^[a-zA-Z0-9_/]+-\d+-', '', code_text, flags=re.MULTILINE)
    
    # Look for req.body destructuring with let or const
    destruct_matches = re.findall(r'(?:let|const)\s*\{([^}]+)\}\s*=\s*req\.body', cleaned_text, re.DOTALL)
    
    for match in destruct_matches:
        # Clean up the match - remove newlines and extra spaces
        match_clean = ' '.join(match.split())
        items = [item.strip() for item in match_clean.split(',')]
        for item in items:
            # Handle renaming (e.g., page_number: pageNum)
            if ':' in item:
                key, val = item.split(':')
                params[key.strip()] = val.strip()
            else:
                clean_item = item.strip()
                if clean_item and not clean_item.startswith('//'):
                    params[clean_item] = clean_item
    
    # Look for direct req.body access
    direct_matches = re.findall(r'req\.body\.(\w+)', code_text)
    for match in direct_matches:
        if match not in params:
            params[match] = match
    
    return params


def extract_query_params(code_lines):
    """Extract query parameters from the code."""
    params = {}
    code_text = '\n'.join(code_lines)
    
    # Look for req.query destructuring
    destruct_matches = re.findall(r'let\s*{([^}]+)}\s*=\s*req\.query', code_text)
    destruct_matches += re.findall(r'const\s*{([^}]+)}\s*=\s*req\.query', code_text)
    
    for match in destruct_matches:
        items = [item.strip() for item in match.split(',')]
        for item in items:
            if ':' in item:
                key, val = item.split(':')
                params[key.strip()] = val.strip()
            else:
                params[item] = item
    
    # Look for direct req.query access
    direct_matches = re.findall(r'req\.query\.(\w+)', code_text)
    for match in direct_matches:
        if match not in params:
            params[match] = match
    
    return params


def extract_route_params(path):
    """Extract route parameters from the path (e.g., /:id)."""
    params = re.findall(r':(\w+)', path)
    return params


def generate_default_body(method, path, body_params, query_params, route_params):
    """Generate a default request body based on extracted parameters."""
    if method in ['GET', 'DELETE']:
        return None
    
    body = {}
    
    # Add common pagination params if detected
    if 'page_number' in body_params or 'page_size' in body_params or 'filters' in body_params:
        if 'page_number' in body_params:
            body['page_number'] = 1
        if 'page_size' in body_params:
            body['page_size'] = 10
        if 'filters' in body_params:
            body['filters'] = {
                "name": "",
                "from": 0,
                "to": 100,
                "active": -1,
                "sort": "d",
                "column": "fill"
            }
        if 'search' in body_params:
            body['search'] = {
                "value": "",
                "regex": False
            }
    
    # Add other detected params with default values
    for param in body_params:
        if param not in body and param not in ['page_number', 'page_size', 'filters', 'search']:
            body[param] = ""
    
    # If no body params found but it's POST/PUT, add empty object
    if not body and method in ['POST', 'PUT']:
        body = {}
    
    return body if body else None


def path_to_filename(file_path, method):
    """Convert file path to posting.yaml filename."""
    # Remove .js extension
    base_name = file_path.replace('.js', '')
    return f"{base_name}.posting.yaml"


def path_to_function_name(file_path):
    """Convert file path to function name (e.g., bins/add -> Bins Add)."""
    # Remove .js extension
    base_name = file_path.replace('.js', '')
    # Split by / and capitalize each part
    parts = base_name.split('/')
    return ' '.join([part.capitalize() for part in parts])


def generate_posting_yaml(endpoint, output_dir):
    """Generate a posting.yaml file for an endpoint."""
    file_path = endpoint['file']
    method = endpoint['method']
    path = endpoint['path']
    has_auth = endpoint['has_auth']
    
    body_params = extract_request_body_params(endpoint['code_lines'])
    query_params = extract_query_params(endpoint['code_lines'])
    route_params = extract_route_params(path)
    
    # Generate the YAML content
    function_name = path_to_function_name(file_path)
    
    # Build the body
    body = generate_default_body(method, path, body_params, query_params, route_params)
    
    # Create the directory structure
    yaml_filename = path_to_filename(file_path, method)
    full_path = os.path.join(output_dir, yaml_filename)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    
    # Generate YAML content
    yaml_content = f"name: {function_name}\n"
    yaml_content += f"method: {method}\n"
    yaml_content += "url: $LOCAL_BASE_URL" + path + "\n"
    
    if body:
        yaml_content += "body:\n"
        yaml_content += "  content: |-\n"
        # Format JSON nicely
        import json
        try:
            body_json = json.dumps(body, indent=4)
            for line in body_json.split('\n'):
                yaml_content += "    " + line + "\n"
        except:
            body_str = str(body).replace("'", '"').replace('True', 'true').replace('False', 'false')
            yaml_content += "    " + body_str + "\n"
        yaml_content += "  content_type: application/json\n"
    
    if has_auth:
        yaml_content += "auth:\n"
        yaml_content += "  type: bearer_token\n"
        yaml_content += "  bearer_token:\n"
        yaml_content += "    token: $TOKEN\n"
    
    yaml_content += "headers:\n"
    yaml_content += "- name: content-type\n"
    yaml_content += "  value: application/json\n"
    
    # Write the file
    with open(full_path, 'w') as f:
        f.write(yaml_content)
    
    return full_path


def main():
    input_file = '/workspace/output.txt'
    output_dir = '/workspace/collection'
    
    print(f"Parsing endpoints from {input_file}...")
    endpoints = parse_endpoints_from_file(input_file)
    
    print(f"Found {len(endpoints)} endpoints")
    
    # Filter out non-API routes (like '/' index routes)
    api_endpoints = [ep for ep in endpoints if not ep['path'] == '/' or 'index' not in ep['file']]
    
    print(f"Generating posting.yaml files for {len(api_endpoints)} API endpoints...")
    
    created_files = []
    for endpoint in api_endpoints:
        try:
            filepath = generate_posting_yaml(endpoint, output_dir)
            created_files.append(filepath)
            print(f"  Created: {filepath}")
        except Exception as e:
            print(f"  Error creating {endpoint['file']}: {e}")
    
    print(f"\nSuccessfully created {len(created_files)} posting.yaml files in {output_dir}")
    
    # Print summary by directory
    dirs = {}
    for f in created_files:
        dir_name = os.path.dirname(f).split('/')[-1]
        if dir_name not in dirs:
            dirs[dir_name] = 0
        dirs[dir_name] += 1
    
    print("\nSummary by directory:")
    for dir_name, count in sorted(dirs.items()):
        print(f"  {dir_name}: {count} files")


if __name__ == '__main__':
    main()
