import os
import sys

src = r'd:\代码\Open-AwA\backend\migrations\add_memory_layers_new.py'
dst = r'd:\代码\Open-AwA\backend\migrations\add_memory_layers.py'

try:
    os.replace(src, dst)
    print('Replace OK')
except Exception as e:
    print(f'Replace Failed: {e}')
    sys.exit(1)
