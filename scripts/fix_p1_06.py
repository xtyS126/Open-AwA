"""
P1-06: Add file size check and ZIP bomb protection to skills.py /install-from-package
"""
path = r"d:\代码\Open-AwA\backend\api\routes\skills.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Add file size limit constant after the last import line
old_import_block = "from config.security import decrypt_secret_value, encrypt_secret_value\nfrom skills.weixin_skill_adapter import WeixinSkillAdapter, WeixinRuntimeConfig, WeixinAdapterError, DEFAULT_BASE_URL, DEFAULT_BOT_TYPE, DEFAULT_QR_BASE_URL"
if "MAX_UPLOAD_SIZE" not in content:
    new_import_block = old_import_block + "\n\nMAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB\nMAX_ZIP_FILES = 100\nMAX_ZIP_EXTRACTION_SIZE = 200 * 1024 * 1024  # 200MB"
    content = content.replace(old_import_block, new_import_block)

# Add file size check before content = await file.read()
old_code = """    try:
        content = await file.read()
        zip_file = zipfile.ZipFile(io.BytesIO(content))
        
        config_files = [name for name in zip_file.namelist() if name.endswith('skill.yaml') or name.endswith('skill.yml')]"""

new_code = """    try:
        if file.size is not None and file.size > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制 ({MAX_UPLOAD_SIZE // (1024*1024)}MB)")
        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制 ({MAX_UPLOAD_SIZE // (1024*1024)}MB)")
        zip_file = zipfile.ZipFile(io.BytesIO(content))
        
        if len(zip_file.namelist()) > MAX_ZIP_FILES:
            raise HTTPException(status_code=400, detail=f"ZIP文件中文件数量超过限制 ({MAX_ZIP_FILES})")
        
        for member in zip_file.namelist():
            if member.startswith('/') or '..' in member:
                raise HTTPException(status_code=400, detail="非法的ZIP文件路径")
            info = zip_file.getinfo(member)
            if info.file_size > MAX_UPLOAD_SIZE:
                raise HTTPException(status_code=400, detail=f"ZIP中单个文件大小超过限制 ({MAX_UPLOAD_SIZE // (1024*1024)}MB)")
        
        config_files = [name for name in zip_file.namelist() if name.endswith('skill.yaml') or name.endswith('skill.yml')]"""

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("P1-06: skills.py /install-from-package updated successfully")
else:
    print("ERROR: old_code not found!")
    idx = content.find("content = await file.read()")
    if idx >= 0:
        print(f"Found at position {idx}")
        print(repr(content[idx-50:idx+200]))
