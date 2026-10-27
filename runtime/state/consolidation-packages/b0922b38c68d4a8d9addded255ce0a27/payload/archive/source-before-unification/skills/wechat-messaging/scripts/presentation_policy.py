"""Business delivery presentation contract, independent of UI and model."""
from pathlib import Path
IMAGE_EXTENSIONS = frozenset({'.png','.jpg','.jpeg','.webp','.gif','.bmp','.tif','.tiff'})
DOCUMENT_EXTENSIONS = frozenset({'.xlsx','.xls','.csv','.docx','.doc','.pdf','.zip'})

def violation(item):
    kind = item.get('type')
    extensions = {Path(str(item.get(key,''))).suffix.lower() for key in ('name','path')}
    if kind == 'file' and extensions & IMAGE_EXTENSIONS:
        return 'screenshot-must-be-inline-image'
    if kind == 'image' and extensions & DOCUMENT_EXTENSIONS:
        return 'document-must-be-file'
    return None

def expected_presentation(item):
    error = violation(item)
    if error:
        raise ValueError(error)
    return {'image':'inline-image','file':'file-card','text':'text-message'}[item['type']]
