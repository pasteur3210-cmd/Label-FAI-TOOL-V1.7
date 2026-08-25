import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from unittest.mock import patch

from label_tool.core import golden_profile_manager as gpm


def _make_docx(path: Path, line: str):
    xml=f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>{line}</w:t></w:r></w:p>
<w:p><w:r><w:t>GPON VoIP Gateway</w:t></w:r></w:p>
<w:p><w:r><w:t>CLASS 1 LASER PRODUCT</w:t></w:r></w:p>
</w:body></w:document>'''
    with ZipFile(path,'w',ZIP_DEFLATED) as z:
        z.writestr('word/document.xml',xml)
        z.writestr('word/media/image1.png',b'PNGDATA')


def _base_profile():
    return {
        'profile_name':'GRG-4297u Chassis Label',
        'profile_version':'1.9.0',
        'profile_status':'BUNDLED',
        'model':'GRG-4297u',
        'label_type':'Chassis Label',
        'label_pn':'680010-378',
        'fixed_fields':{'model':'GRG-4297u','ip':'192.168.1.1'},
        'live':{'required_items':['Fixed: model']},
        'image_inspection':{'role_items':{}},
    }


def test_grg4355_import_cannot_inherit_grg4297_identity(tmp_path):
    src=tmp_path/'680010-305 GRG-4355u-DIG-P1 Chassis Label.docx'
    _make_docx(src,'680010-305 GRG-4355u-DIG-P1 Chassis Label')
    profile_root=tmp_path/'profiles'; profile_root.mkdir()
    with patch.object(gpm,'external_profile_dir',lambda: profile_root):
        out,profile=gpm.build_dynamic_profile(str(src),_base_profile(),'GRG-4297u Dynamic Label')
    assert profile['model'].lower()=='grg-4355u'
    assert profile['label_type']=='Chassis Label'
    assert profile['label_pn']=='680010-305'
    assert profile['profile_name'].lower()=='grg-4355u chassis label'
    assert '4297' not in profile['profile_name'].lower()
    assert out.name.lower()=='grg-4355u_chassis_label_680010-305.json'
    assert gpm.dynamic_identity_errors(profile,out)==[]
    disk=json.loads(out.read_text(encoding='utf-8'))
    assert disk['profile_identity']['model'].lower()=='grg-4355u'
    assert disk['profile_identity']['source_sha256']==disk['golden_import']['source_sha256']


def test_legacy_wrong_dynamic_identity_is_rejected():
    bad={
        'dynamic_profile':True,
        'profile_name':'GRG-4297u Dynamic Label',
        'profile_version':'1.9.1',
        'model':'GRG-4355u',
        'label_type':'Chassis Label',
        'label_pn':'680010-305',
        'live':{'required_items':[]},
        'golden_import':{'source_sha256':'abc'},
    }
    errs=gpm.validate_profile_structure(bad,Path('GRG-4297u_Dynamic_Label.json'))
    assert errs
    assert any('Profile name mismatch' in e for e in errs)
    assert any('filename mismatch' in e for e in errs)


def test_unknown_model_never_falls_back_to_seed_model(tmp_path):
    src=tmp_path/'generic_chassis_label.docx'
    _make_docx(src,'Chassis Label')
    profile_root=tmp_path/'profiles'; profile_root.mkdir()
    with patch.object(gpm,'external_profile_dir',lambda: profile_root):
        try:
            gpm.build_dynamic_profile(str(src),_base_profile())
        except ValueError as exc:
            assert 'Cannot determine Model' in str(exc)
        else:
            raise AssertionError('Expected missing-model import to fail instead of inheriting GRG-4297u')


def test_app_no_longer_seeds_dynamic_profile_name_from_current_model():
    source=Path('label_tool/app.py').read_text(encoding='utf-8')
    assert 'suggested=f"{base.get(' not in source
    assert 'build_dynamic_profile(source,base)' in source
