"""
P1-07: Add file size check and ZIP bomb protection to plugins.py /upload
"""
path = r"d:\代码\Open-AwA\backend\api\routes\plugins.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Add MAX_UPLOAD_SIZE and MAX_ZIP_FILES constants after last import
old_import_block = "from loguru import logger"
new_import_block = old_import_block + "\n\nMAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB\nMAX_ZIP_FILES = 100\nMAX_ZIP_EXTRACTION_SIZE = 200 * 1024 * 1024  # 200MB"
if "MAX_UPLOAD_SIZE" not in content:
    content = content.replace(old_import_block, new_import_block)

# Add file size check before content = await file.read()
old_code = """    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files are supported")
        
    content = await file.read()"""

new_code = """    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files are supported")
    if file.size is not None and file.size > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail=f"File size exceeds limit ({MAX_UPLOAD_SIZE // (1024*1024)}MB)")
        
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail=f"File size exceeds limit ({MAX_UPLOAD_SIZE // (1024*1024)}MB)")"""

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("P1-07: plugins.py /upload updated successfully")
else:
    print("ERROR: old_code not found!")
    # Try to find it
    idx = content.find("if not file.filename")
    if idx >= 0:
        print(f"Found at position {idx}")
        print(repr(content[idx:idx+180]))
    
# Add ZIP bomb protection inside the zip extraction section
old_zip_check = """        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for member in z.namelist():
                if member.startswith('/') or '..' in member:
                    raise HTTPException(status_code=400, detail="Invalid zip file structure")
            
            z.extractall(temp_dir)"""

new_zip_check = """        with zipfile.ZipFile(io.BytesIO(content)) as z:
            all_members = z.namelist()
            if len(all_members) > MAX_ZIP_FILES:
                raise HTTPException(status_code=400, detail=f"ZIP file contains too many files ({len(all_members)} > {MAX_ZIP_FILES})")
            total_size = 0
            for member in all_members:
                if member.startswith('/') or '..' in member:
                    raise HTTPException(status_code=400, detail="Invalid zip file structure")
                info = z.getinfo(member)
                total_size += info.file_size
                if info.file_size > MAX_UPLOAD_SIZE:
                    raise HTTPException(status_code=400, detail=f"Individual file in ZIP exceeds size limit ({MAX_UPLOAD_SIZE // (1024*1024)}MB)")
            if total_size > MAX_ZIP_EXTRACTION_SIZE:
                raise HTTPException(status_code=400, detail=f"Total extraction size exceeds limit ({MAX_ZIP_EXTRACTION_SIZE // (1024*1024)}MB)")
            
            z.extractall(temp_dir)"""

if old_zip_check in content:
    content = content.replace(old_zip_check, new_zip_check)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("P1-07: ZIP bomb protection added to plugins.py")
else:
    print("WARNING: old_zip_check not found!")
    idx = content.find("with zipfile.ZipFile")
    if idx >= 0:
        print(f"Found at position {idx}")
        print(repr(content[idx:idx+200]))
