#!/usr/bin/env python3
"""
Keycap Slicer Bridge v2.1
ブラウザ(Keycap Generator)からスライサーへモデルを直接転送するブリッジアプリ
"""

import os
import sys
import json
import tempfile
import subprocess
import threading
import time
import shutil
from http.server import HTTPServer, BaseHTTPRequestHandler
try:
    import cgi
except ImportError:
    cgi = None
import io
import re
import zipfile

# === Configuration ===
PORT = 19876
APP_NAME = "Keycap Slicer Bridge"
VERSION = "2.6.2"
APP_DIR_NAME = "KeycapSlicerBridge"
INSTALL_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), APP_DIR_NAME)
TEMP_DIR = os.path.join(tempfile.gettempdir(), "keycap-slicer-bridge")
CONFIG_FILE = os.path.join(INSTALL_DIR, "config.json")
REG_KEY_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
REG_VALUE_NAME = "KeycapSlicerBridge"

ALLOWED_ORIGINS = [
    "https://keycapgenerator.com",
    "https://www.keycapgenerator.com",
    "http://localhost",
    "http://127.0.0.1",
    "https://sireai.github.io",
    "https://hololocheck.github.io",
    "null",
]

SLICER_PATHS = {
    "bambu": [
        os.path.expandvars(r"%ProgramFiles%\Bambu Studio\bambu-studio.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Bambu Studio\bambu-studio.exe"),
        os.path.expandvars(r"%LocalAppData%\Programs\Bambu Studio\bambu-studio.exe"),
    ],
    "orca": [
        os.path.expandvars(r"%ProgramFiles%\OrcaSlicer\orca-slicer.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\OrcaSlicer\orca-slicer.exe"),
        os.path.expandvars(r"%LocalAppData%\Programs\OrcaSlicer\orca-slicer.exe"),
    ]
}


ALLOWED_EXTENSIONS = {'.stl', '.3mf', '.obj', '.step', '.stp'}

# =====================================================
# Project Filament Scanner v2.5
# VERIFIED data formats from user's actual .3mf:
#   project_settings.config → JSON: {"filament_colour":["#B5","#21",...]}
#   slice_info.config       → XML:  <filament id="1" color="#B5..." type="PLA"/>
#   Config/filament/*.json  → JSON: {"filament_colour":["#FF"],...}
# BambuStudio.conf          → JSON (25KB+, may have extra data after main object)
# =====================================================

import xml.etree.ElementTree as ET



def _normalize_hex(v):
    """Normalize hex color string to #RRGGBB uppercase."""
    if v is None:
        return ''
    if isinstance(v, list):
        v = v[0] if v else ''
    v = str(v).strip().strip('"\'').strip()
    if not v:
        return ''
    if re.match(r'^#[0-9a-fA-F]{6}$', v):
        return v.upper()
    if re.match(r'^#[0-9a-fA-F]{8}$', v):
        return v[:7].upper()
    if re.match(r'^#[0-9a-fA-F]{3}$', v):
        return f'#{v[1]*2}{v[2]*2}{v[3]*2}'.upper()
    if re.match(r'^[0-9a-fA-F]{6}$', v):
        return f'#{v}'.upper()
    return ''


def _try_read_file(path, max_bytes=50*1024*1024):
    """Read text file with encoding fallbacks. Default 50MB."""
    for enc in ('utf-8-sig', 'utf-8', 'cp932', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read(max_bytes)
        except (UnicodeDecodeError, UnicodeError):
            continue
        except (PermissionError, OSError):
            return None
    return None


def _try_parse_json(text):
    """Parse JSON tolerantly (trailing commas, comments, extra data after JSON)."""
    if not text:
        return None, 'empty'
    text = text.lstrip('\ufeff')
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        err1 = str(e)

    # Fallback 1: raw_decode — handles "Extra data" (valid JSON + trailing garbage)
    try:
        decoder = json.JSONDecoder()
        obj, end_idx = decoder.raw_decode(text)
        return obj, None
    except json.JSONDecodeError:
        pass

    # Fallback 2: remove trailing commas
    cleaned = re.sub(r',\s*([}\]])', r'\1', text)
    try:
        return json.loads(cleaned), None
    except json.JSONDecodeError:
        pass

    # Fallback 3: raw_decode on cleaned
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned)
        return obj, None
    except json.JSONDecodeError:
        pass

    # Fallback 4: remove // comments
    lines = [l for l in cleaned.splitlines() if not l.lstrip().startswith('//')]
    cleaned2 = '\n'.join(lines)
    try:
        return json.loads(cleaned2), None
    except json.JSONDecodeError:
        pass
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned2)
        return obj, None
    except json.JSONDecodeError:
        pass

    return None, err1


def _read_conf(slicer_type):
    """Read BambuStudio.conf FULLY (no byte truncation) → (dict, path, error)."""
    app = 'BambuStudio' if slicer_type != 'orca' else 'OrcaSlicer'
    appdata = os.environ.get('APPDATA', '')
    conf_path = os.path.join(appdata, app, f'{app}.conf')
    if not os.path.isfile(conf_path):
        return None, conf_path, 'file not found'
    text = _try_read_file(conf_path)
    if text is None:
        return None, conf_path, 'cannot read'
    data, err = _try_parse_json(text)
    if data is None:
        return None, conf_path, f'parse error: {err}'
    return data, conf_path, None


# ── INI parser ──

def _parse_ini_settings(text):
    """Parse INI-style config (key = value per line) to dict."""
    settings = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(';') or line.startswith('#'):
            continue
        idx = line.find('=')
        if idx < 0:
            continue
        settings[line[:idx].strip()] = line[idx + 1:].strip()
    return settings


# ── Colour key extractor (works for both INI dicts and JSON dicts) ──

def _filaments_from_colour_key(settings):
    """Extract filament list from dict with filament_colour-like key."""
    colours_raw = None
    for ck in ('filament_colour', 'default_filament_colour',
               'filament_color', 'default_filament_color'):
        val = settings.get(ck)
        if val:
            colours_raw = val
            break
    if not colours_raw:
        return None

    # Handle list (JSON) or string (INI semicolons)
    if isinstance(colours_raw, list):
        colours = [str(c).strip() for c in colours_raw]
    else:
        colours = [c.strip() for c in str(colours_raw).split(';')]

    names_raw = settings.get('filament_settings_id', '')
    types_raw = settings.get('filament_type', '')
    vendors_raw = settings.get('filament_vendor', '')
    def _split(v):
        if isinstance(v, list):
            return [str(x).strip() for x in v]
        return [x.strip() for x in str(v).split(';')] if v else []
    names = _split(names_raw)
    types = _split(types_raw)
    vendors = _split(vendors_raw)

    filaments = []
    for i, raw in enumerate(colours):
        colour = _normalize_hex(raw)
        if not colour:
            continue
        name = names[i] if i < len(names) else ''
        name = re.sub(r'\s*@\s*.+$', '', str(name)).strip()
        ftype = types[i] if i < len(types) else 'PLA'
        vendor = vendors[i] if i < len(vendors) else ''
        filaments.append({'slot': i+1, 'name': name, 'color': colour,
                          'type': ftype, 'vendor': vendor})
    return filaments if filaments else None


# ── .3mf multi-source extraction ──

def _extract_all_from_3mf(filepath):
    """Open .3mf ZIP and try ALL known data sources for filament info."""
    debug = {'file': filepath, 'sources_tried': []}
    try:
        z = zipfile.ZipFile(filepath, 'r')
    except (zipfile.BadZipFile, PermissionError, OSError) as e:
        debug['open_error'] = str(e)
        return None, None, debug
    namelist = z.namelist()

    for tryf in (_src_A_project_settings, _src_B_slice_info_xml,
                 _src_C_config_filament_json, _src_D_3dmodel_xml):
        result = tryf(z, namelist, debug)
        if result:
            z.close()
            return result
    z.close()
    return None, None, debug


def _src_A_project_settings(z, namelist, debug):
    """Source A: Metadata/project_settings.config (can be JSON or INI)."""
    src = {'name': 'A_project_settings'}
    for cfg in namelist:
        if 'project_settings' not in cfg.lower() or not cfg.lower().endswith('.config'):
            continue
        raw = z.read(cfg).decode('utf-8', errors='replace')
        src['size'] = len(raw)
        stripped = raw.lstrip()

        if stripped.startswith('{'):
            # JSON format (BambuStudio newer versions)
            src['format'] = 'json'
            data, err = _try_parse_json(raw)
            if data and isinstance(data, dict):
                filaments = _filaments_from_colour_key(data)
                if filaments:
                    src['status'] = 'ok_json'
                    debug['sources_tried'].append(src)
                    return filaments, f'project_settings_json:{cfg}', debug
                ckeys = [k for k in data if 'colour' in k.lower() or 'color' in k.lower()]
                src['colour_keys_found'] = ckeys[:10]
                src['status'] = 'no_colour_key_json'
            else:
                src['status'] = 'json_parse_fail'
                src['error'] = err
        else:
            # INI format
            src['format'] = 'ini'
            settings = _parse_ini_settings(raw)
            filaments = _filaments_from_colour_key(settings)
            if filaments:
                src['status'] = 'ok_ini'
                debug['sources_tried'].append(src)
                return filaments, f'project_settings_ini:{cfg}', debug
            src['status'] = 'no_colour_key_ini'
        break
    else:
        src['status'] = 'file_not_found'
    debug['sources_tried'].append(src)
    return None


def _src_B_slice_info_xml(z, namelist, debug):
    """Source B: Metadata/slice_info.config — XML with <filament> tags.
    Expected format:
      <config>
        <plate>
          <filament id="1" type="PLA" color="#FF0000" used="1"/>
          <filament id="2" type="PLA" color="#00FF00" used="0"/>
        </plate>
      </config>
    """
    src = {'name': 'B_slice_info_xml'}
    for cfg in namelist:
        if 'slice_info' not in cfg.lower() or not cfg.lower().endswith('.config'):
            continue
        raw = z.read(cfg).decode('utf-8', errors='replace')
        src['size'] = len(raw)
        if not raw.lstrip().startswith('<'):
            src['status'] = 'not_xml'
            break
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            src['status'] = f'xml_error:{e}'
            break

        felems = root.findall('.//filament')
        src['filament_tags'] = len(felems)
        if not felems:
            tags = sorted({elem.tag for elem in root.iter()})
            src['available_tags'] = tags[:20]
            src['status'] = 'no_filament_tags'
            break

        filaments = []
        for elem in felems:
            fid = elem.get('id', '')
            color = _normalize_hex(elem.get('color', '') or elem.get('colour', ''))
            ftype = elem.get('type', 'PLA')
            used = elem.get('used', '1')
            name = elem.get('sub_path', '') or elem.get('filament_settings_id', '')
            name = re.sub(r'\s*@\s*.+$', '', name).strip()
            if not name:
                name = f'{ftype} #{fid}'
            if color:
                slot = int(fid) if fid.isdigit() else len(filaments) + 1
                filaments.append({'slot': slot, 'name': name, 'color': color,
                                  'type': ftype, 'vendor': '', 'used': used})
        if filaments:
            src['status'] = 'ok'
            debug['sources_tried'].append(src)
            return filaments, f'slice_info_xml:{cfg}', debug
        # Has <filament> tags but no color attribute
        src['status'] = 'tags_no_color'
        if felems:
            src['sample_attribs'] = dict(felems[0].attrib)
        break
    else:
        src['status'] = 'file_not_found'
    debug['sources_tried'].append(src)
    return None


def _src_C_config_filament_json(z, namelist, debug):
    """Source C: Config/filament/*.json — embedded filament preset JSONs."""
    src = {'name': 'C_config_filament_json'}
    fjsons = [f for f in namelist
              if f.lower().startswith('config/filament/') and f.lower().endswith('.json')]
    if not fjsons:
        fjsons = [f for f in namelist
                  if 'filament' in f.lower() and f.lower().endswith('.json')]
    src['files_found'] = len(fjsons)
    if not fjsons:
        src['status'] = 'no_json_files'
        debug['sources_tried'].append(src)
        return None

    fjsons.sort()
    filaments = []
    src['parsed'] = []
    for idx, fj in enumerate(fjsons[:16]):
        try:
            raw = z.read(fj).decode('utf-8', errors='replace')
            data, err = _try_parse_json(raw)
            if not data or not isinstance(data, dict):
                src['parsed'].append({'file': os.path.basename(fj), 'error': err or 'not dict'})
                continue
            colour = ''
            for ck in ('filament_colour', 'default_filament_colour',
                        'filament_color', 'default_filament_color', 'color'):
                val = data.get(ck)
                if isinstance(val, list):
                    val = val[0] if val else ''
                colour = _normalize_hex(val)
                if colour:
                    break
            name = data.get('name', '') or data.get('filament_settings_id', '')
            if isinstance(name, list):
                name = name[0] if name else ''
            name = re.sub(r'\s*@\s*.+$', '', str(name)).strip() or os.path.splitext(os.path.basename(fj))[0]
            ftype = data.get('filament_type', ['PLA'])
            if isinstance(ftype, list):
                ftype = ftype[0] if ftype else 'PLA'
            vendor = data.get('filament_vendor', [''])
            if isinstance(vendor, list):
                vendor = vendor[0] if vendor else ''
            src['parsed'].append({'file': os.path.basename(fj), 'color': colour, 'name': name})
            if colour:
                filaments.append({'slot': idx+1, 'name': name, 'color': colour,
                                  'type': ftype, 'vendor': vendor})
        except Exception as e:
            src['parsed'].append({'file': os.path.basename(fj), 'error': str(e)})

    if filaments:
        src['status'] = 'ok'
        debug['sources_tried'].append(src)
        return filaments, f'config_json:{len(filaments)} files', debug
    src['status'] = 'no_colors_in_json'
    debug['sources_tried'].append(src)
    return None


def _src_D_3dmodel_xml(z, namelist, debug):
    """Source D: 3D/3dmodel.model — standard 3MF <basematerials>."""
    src = {'name': 'D_3dmodel_xml'}
    mfiles = [f for f in namelist if f.lower() == '3d/3dmodel.model']
    if not mfiles:
        src['status'] = 'file_not_found'
        debug['sources_tried'].append(src)
        return None
    try:
        raw = z.read(mfiles[0]).decode('utf-8', errors='replace')
        raw_ns = re.sub(r'\sxmlns="[^"]*"', '', raw, count=5)
        root = ET.fromstring(raw_ns)
    except (ET.ParseError, Exception) as e:
        src['status'] = f'parse_error:{e}'
        debug['sources_tried'].append(src)
        return None
    bases = root.findall('.//basematerials')
    if not bases:
        src['status'] = 'no_basematerials'
        debug['sources_tried'].append(src)
        return None
    filaments = []
    for bm in bases:
        for i, base in enumerate(bm):
            color = _normalize_hex(base.get('displaycolor', ''))
            name = base.get('name', f'Material {i+1}')
            if color:
                filaments.append({'slot': i+1, 'name': name, 'color': color,
                                  'type': 'PLA', 'vendor': ''})
    if filaments:
        src['status'] = 'ok'
        debug['sources_tried'].append(src)
        return filaments, f'3dmodel_basematerials', debug
    src['status'] = 'no_colors'
    debug['sources_tried'].append(src)
    return None


# ── .3mf file collection ──

def _collect_3mf_files(slicer_type, conf_data=None):
    """Gather .3mf files, newest first, deduped."""
    found = []
    seen = set()
    appdata = os.environ.get('APPDATA', '')
    userprofile = os.environ.get('USERPROFILE', '')
    app = 'BambuStudio' if slicer_type != 'orca' else 'OrcaSlicer'

    def add(path):
        if not path or not isinstance(path, str):
            return
        path = path.replace('/', os.sep)
        if not path.lower().endswith('.3mf'):
            return
        np = os.path.normcase(os.path.abspath(path))
        if np in seen:
            return
        seen.add(np)
        if os.path.isfile(path):
            try:
                found.append((os.path.getmtime(path), path))
            except OSError:
                pass

    if conf_data:
        rp = conf_data.get('recent_projects', [])
        if isinstance(rp, list):
            for item in rp:
                if isinstance(item, str):
                    add(item)
                elif isinstance(item, dict):
                    add(item.get('path', ''))
        elif isinstance(rp, dict):
            # BambuStudio format: {"001": "path", "002": "path", ...}
            for key in sorted(rp.keys()):
                val = rp[key]
                if isinstance(val, str):
                    add(val)
    for sub in ('', 'cache', 'projects'):
        d = os.path.join(appdata, app, sub) if sub else os.path.join(appdata, app)
        if os.path.isdir(d):
            try:
                for e in os.scandir(d):
                    if e.is_file(): add(e.path)
            except (PermissionError, OSError):
                pass
    for name in ('Desktop', 'Documents', 'Downloads', '3D Objects'):
        d = os.path.join(userprofile, name)
        if os.path.isdir(d):
            try:
                for e in os.scandir(d):
                    if e.is_file(): add(e.path)
            except (PermissionError, OSError):
                pass
    found.sort(reverse=True)
    return found


# ── Main entry points ──

def _build_filament_color_map(user_dir, app, appdata):
    """Build {preset_name: '#RRGGBB'} map from user + system filament presets."""
    color_map = {}

    # 1) User presets: %APPDATA%\BambuStudio\user\[UID]\filament\*.json
    if os.path.isdir(user_dir):
        for uid in os.listdir(user_dir):
            fil_dir = os.path.join(user_dir, uid, 'filament')
            if os.path.isdir(fil_dir):
                _scan_filament_dir(fil_dir, color_map)

    # 2) System presets: %APPDATA%\BambuStudio\system\*\filament\
    sys_dir = os.path.join(appdata, app, 'system')
    if os.path.isdir(sys_dir):
        for vendor in os.listdir(sys_dir):
            fil_dir = os.path.join(sys_dir, vendor, 'filament')
            if os.path.isdir(fil_dir):
                _scan_filament_dir(fil_dir, color_map)

    # 3) Program files resources
    for pf in [os.environ.get('ProgramFiles', ''), os.environ.get('ProgramFiles(x86)', '')]:
        if not pf:
            continue
        prog_dir = os.path.join(pf, 'Bambu Studio', 'resources', 'profiles')
        if os.path.isdir(prog_dir):
            for vendor in os.listdir(prog_dir):
                fil_dir = os.path.join(prog_dir, vendor, 'filament')
                if os.path.isdir(fil_dir):
                    _scan_filament_dir(fil_dir, color_map)

    return color_map


def _scan_filament_dir(fil_dir, color_map):
    """Scan a directory of .json filament presets and add to color_map."""
    try:
        for entry in os.scandir(fil_dir):
            if not entry.is_file():
                # Could be subdirectory with more JSONs
                if entry.is_dir():
                    try:
                        for sub_entry in os.scandir(entry.path):
                            if sub_entry.is_file() and sub_entry.name.lower().endswith('.json'):
                                _read_filament_preset(sub_entry.path, color_map)
                    except (PermissionError, OSError):
                        pass
                continue
            if entry.name.lower().endswith('.json'):
                _read_filament_preset(entry.path, color_map)
            elif entry.name.lower().endswith('.info'):
                # BambuStudio .info format (INI-style)
                _read_filament_info(entry.path, color_map)
    except (PermissionError, OSError):
        pass


def _read_filament_preset(filepath, color_map):
    """Read a single filament .json preset and add name→color to map."""
    try:
        text = _try_read_file(filepath)
        if not text:
            return
        data, _ = _try_parse_json(text)
        if not data or not isinstance(data, dict):
            return
        # Get name
        name = ''
        for nk in ('name', 'filament_settings_id'):
            val = data.get(nk)
            if isinstance(val, list):
                val = val[0] if val else ''
            if val:
                name = str(val).strip()
                break
        if not name:
            name = os.path.splitext(os.path.basename(filepath))[0]
        # Get color
        for ck in ('filament_colour', 'default_filament_colour', 'filament_color', 'color'):
            val = data.get(ck)
            if isinstance(val, list):
                val = val[0] if val else ''
            colour = _normalize_hex(val)
            if colour:
                color_map[name] = colour
                # Also map without @printer suffix
                base = re.sub(r'\s*@\s*.+$', '', name).strip()
                if base and base != name:
                    color_map[base] = colour
                # Also lowercase
                color_map[name.lower()] = colour
                color_map[base.lower()] = colour
                break
    except Exception:
        pass


def _read_filament_info(filepath, color_map):
    """Read .info file (INI format) for filament name→color."""
    try:
        text = _try_read_file(filepath)
        if not text:
            return
        settings = _parse_ini_settings(text)
        name = settings.get('name', '') or os.path.splitext(os.path.basename(filepath))[0]
        for ck in ('filament_colour', 'default_filament_colour', 'filament_color'):
            colour = _normalize_hex(settings.get(ck, ''))
            if colour:
                color_map[name] = colour
                color_map[name.lower()] = colour
                break
    except Exception:
        pass


def get_project_filaments(slicer_type='bambu'):
    """Main: find and extract project filaments."""
    debug = {'strategies': []}
    app = 'BambuStudio' if slicer_type != 'orca' else 'OrcaSlicer'
    appdata = os.environ.get('APPDATA', '')

    conf_data, conf_path, conf_err = _read_conf(slicer_type)
    debug['conf'] = {'path': conf_path, 'ok': conf_data is not None, 'error': conf_err}

    # ── Strategy 0: conf JSON → filament colors ──
    # BambuStudio: presets.filament_colors = "#DCD,#FFF,..." (comma-separated string)
    # OrcaSlicer:  orca_presets = [{machine:"X", filament_colors:"#A,#B"}, ...] (array per printer)
    s0 = {'name': '0_conf_json_presets'}
    if conf_data and isinstance(conf_data, dict):
        found_colors = ''
        found_names = []
        found_in = ''

        # ── Path A: BambuStudio-style presets.filament_colors (string) ──
        presets = conf_data.get('presets', {})
        if isinstance(presets, dict):
            s0['presets_keys'] = list(presets.keys())[:20]
            for ck in ('filament_colors', 'filament_colours', 'filament_multi_colors'):
                val = presets.get(ck, '')
                if val and isinstance(val, str) and '#' in val:
                    found_colors = val
                    found_in = f'presets.{ck}'
                    break
            if found_colors:
                fil = presets.get('filaments', [])
                if isinstance(fil, list) and fil and fil[0] is not None:
                    found_names = fil

        # ── Path B: OrcaSlicer-style orca_presets array ──
        if not found_colors:
            orca_presets = conf_data.get('orca_presets', [])
            if isinstance(orca_presets, list) and orca_presets:
                s0['orca_presets_count'] = len(orca_presets)
                # Get currently selected machine
                current_machine = ''
                if isinstance(presets, dict):
                    current_machine = presets.get('machine', '')
                s0['current_machine'] = current_machine

                # Find matching entry (try exact match, then partial)
                matched_entry = None
                for entry in orca_presets:
                    if not isinstance(entry, dict):
                        continue
                    em = entry.get('machine', '')
                    if em == current_machine:
                        matched_entry = entry
                        break
                # Partial match (machine name without suffix)
                if not matched_entry and current_machine:
                    cm_base = current_machine.split('_')[0].strip()
                    for entry in orca_presets:
                        if not isinstance(entry, dict):
                            continue
                        em = entry.get('machine', '')
                        if cm_base and cm_base in em:
                            matched_entry = entry
                            break
                # Last resort: use the last entry (most recently used printer)
                if not matched_entry:
                    matched_entry = orca_presets[-1] if orca_presets else None

                if matched_entry:
                    s0['matched_machine'] = matched_entry.get('machine', '(none)')
                    fc = matched_entry.get('filament_colors', '')
                    if fc and '#' in fc:
                        found_colors = fc
                        found_in = 'orca_presets.filament_colors'
                        # Extract names from filament, filament_01, filament_02, ...
                        names = []
                        base = matched_entry.get('filament', '')
                        if base:
                            names.append(base)
                        for idx in range(1, 32):
                            key = f'filament_{idx:02d}'
                            val = matched_entry.get(key, '')
                            if val:
                                names.append(val)
                            else:
                                break
                        if names:
                            found_names = names

        s0['found_colors'] = str(found_colors)[:200] if found_colors else '(none)'
        s0['found_names'] = len(found_names)
        s0['found_in'] = found_in or '(none)'

        if found_colors:
            sep = ',' if ',' in found_colors else ';'
            colours = [c.strip() for c in found_colors.split(sep)]
            filaments = []
            for i in range(max(len(colours), len(found_names))):
                colour = _normalize_hex(colours[i]) if i < len(colours) else ''
                name = ''
                if i < len(found_names) and found_names[i] is not None:
                    name = str(found_names[i])
                base_name = re.sub(r'\s*@\s*.+$', '', name).strip()
                ftype = 'PLA'
                for t in ('PETG', 'ABS', 'TPU', 'ASA', 'PA', 'PC', 'PVA'):
                    if t.lower() in name.lower():
                        ftype = t
                        break
                filaments.append({
                    'slot': i+1, 'name': base_name, 'color': colour or '#808080',
                    'type': ftype, 'vendor': ''
                })
            if filaments:
                has_colors = sum(1 for f in filaments if f['color'] != '#808080')
                s0['status'] = f'ok:{has_colors}_colors/{len(filaments)}_slots'
                debug['strategies'].append(s0)
                return {'status':'ok','count':len(filaments),'filaments':filaments,
                        'source':f'conf:{found_in}','debug':debug}
        s0['status'] = 'no_colors_found'
    else:
        s0['status'] = 'conf_unavailable'
    debug['strategies'].append(s0)

    # ── Strategy 1: conf → last_backup_path → Metadata/ ──
    s1 = {'name': '1_backup_path'}
    if conf_data:
        backup_path = ''
        app_sec = conf_data.get('app', {})
        if isinstance(app_sec, dict):
            backup_path = app_sec.get('last_backup_path', '')
        if not backup_path:
            backup_path = conf_data.get('last_backup_path', '')
        if backup_path:
            backup_path = backup_path.replace('/', os.sep)
            s1['path'] = backup_path
            meta_dir = os.path.join(backup_path, 'Metadata')
            if os.path.isdir(meta_dir):
                for cfg_name in ('project_settings.config', 'slice_info.config'):
                    cfg_file = os.path.join(meta_dir, cfg_name)
                    if not os.path.isfile(cfg_file):
                        continue
                    text = _try_read_file(cfg_file)
                    if not text:
                        continue
                    filaments = _try_parse_any_format(text)
                    if filaments:
                        s1['status'] = f'ok:{cfg_name}'
                        debug['strategies'].append(s1)
                        return {'status':'ok','count':len(filaments),'filaments':filaments,
                                'source':f'backup:{cfg_name}','debug':debug}
                s1['status'] = 'no_colour_in_backup'
                try: s1['metadata_files'] = os.listdir(meta_dir)[:15]
                except: pass
            else:
                s1['status'] = 'metadata_dir_missing'
        else:
            s1['status'] = 'no_backup_path'
    else:
        s1['status'] = 'conf_unavailable'
    debug['strategies'].append(s1)

    # ── Strategy 2: %TEMP% model dir scan ──
    s2 = {'name': '2_temp_scan'}
    temp = tempfile.gettempdir()
    temp_dirs = ['bamboo_model']
    if slicer_type == 'orca':
        temp_dirs = ['orcaslicer_model', 'orca_model', 'bamboo_model']
    for td in temp_dirs:
        model_root = os.path.join(temp, td)
        s2['root'] = model_root
        if not os.path.isdir(model_root):
            continue
        configs = []
        for rd, dirs, files in os.walk(model_root):
            for fn in files:
                if fn.lower().endswith('.config'):
                    fp = os.path.join(rd, fn)
                    try: configs.append((os.path.getmtime(fp), fp))
                    except OSError: pass
        configs.sort(reverse=True)
        s2['configs_found'] = len(configs)
        for _, fp in configs[:10]:
            text = _try_read_file(fp)
            if text:
                filaments = _try_parse_any_format(text)
                if filaments:
                    s2['status'] = f'ok:{fp}'
                    debug['strategies'].append(s2)
                    return {'status':'ok','count':len(filaments),'filaments':filaments,
                            'source':f'temp:{fp}','debug':debug}
    s2['status'] = 'no_colour_in_temp'
    debug['strategies'].append(s2)

    # ── Strategy 3: .3mf files (multi-source extraction) ──
    s3 = {'name': '3_3mf_files'}
    all_3mf = _collect_3mf_files(slicer_type, conf_data)
    s3['total'] = len(all_3mf)
    s3['files'] = [os.path.basename(p) for _, p in all_3mf[:8]]
    s3['checked'] = []
    for _, path in all_3mf[:20]:
        filaments, source, exdebug = _extract_all_from_3mf(path)
        check = {'file': os.path.basename(path),
                 'sources': [s.get('name','?')+':'+s.get('status','?')
                             for s in exdebug.get('sources_tried', [])]}
        if filaments:
            check['count'] = len(filaments)
            s3['checked'].append(check)
            s3['matched'] = path
            debug['strategies'].append(s3)
            return {'status':'ok','count':len(filaments),'filaments':filaments,
                    'source':f'3mf:{path}|{source}','debug':debug}
        s3['checked'].append(check)
    s3['status'] = 'none_matched'
    debug['strategies'].append(s3)
    return {'status':'empty','count':0,'filaments':[],'debug':debug}


def _try_parse_any_format(text):
    """Try JSON, XML, INI to extract filaments from a config text."""
    stripped = text.lstrip()
    if stripped.startswith('{'):
        data, _ = _try_parse_json(text)
        if data and isinstance(data, dict):
            return _filaments_from_colour_key(data)
    elif stripped.startswith('<'):
        try:
            root = ET.fromstring(text)
            felems = root.findall('.//filament')
            filaments = []
            for elem in felems:
                color = _normalize_hex(elem.get('color', ''))
                if color:
                    fid = elem.get('id', '')
                    slot = int(fid) if fid.isdigit() else len(filaments)+1
                    ftype = elem.get('type', 'PLA')
                    filaments.append({'slot':slot,'name':f'{ftype} #{fid}',
                        'color':color,'type':ftype,'vendor':''})
            if filaments:
                return filaments
        except ET.ParseError:
            pass
    else:
        return _filaments_from_colour_key(_parse_ini_settings(text))
    return None


def debug_slicer_conf(slicer_type='bambu'):
    """Diagnostic: dump conf contents including INI [presets] tail."""
    result = {}
    app = 'BambuStudio' if slicer_type != 'orca' else 'OrcaSlicer'
    appdata = os.environ.get('APPDATA', '')

    conf_path = os.path.join(appdata, app, f'{app}.conf')
    result['conf_path'] = conf_path
    result['conf_exists'] = os.path.isfile(conf_path)
    if os.path.isfile(conf_path):
        raw = _try_read_file(conf_path)
        if raw:
            result['conf_size'] = len(raw)
            result['conf_first_500'] = raw[:500]
            # CRITICAL: show the TAIL (where [presets] section lives!)
            result['conf_last_2000'] = raw[-2000:]

            # Try JSON parse (gets the first JSON object)
            data, err = _try_parse_json(raw)
            if data:
                result['conf_json_parsed'] = True
                result['conf_json_keys'] = sorted(data.keys())
                # Dump ALL potentially relevant sections
                for k in ('presets', 'orca_presets', 'filaments', 'filament',
                          'filament_colour', 'filament_color', 'custom_color_list'):
                    if k in data:
                        val = data[k]
                        if isinstance(val, (dict, list)):
                            dumped = json.dumps(val, ensure_ascii=False)
                            result[f'conf_json_{k}'] = json.loads(dumped) if len(dumped) < 2000 else dumped[:2000]
                        else:
                            result[f'conf_json_{k}'] = val
                app_sec = data.get('app', {})
                if isinstance(app_sec, dict):
                    result['conf_last_backup'] = app_sec.get('last_backup_path', '(none)')
            else:
                result['conf_json_parsed'] = False
                result['conf_json_error'] = err

            # Parse INI sections (after JSON or standalone)
            ini_sections = _parse_conf_ini_sections(raw)
            result['conf_ini_sections'] = list(ini_sections.keys())
            if 'presets' in ini_sections:
                result['conf_presets'] = ini_sections['presets']
            # Show ALL filament-related keys from any INI section
            for sec_name, sec_data in ini_sections.items():
                for k, v in sec_data.items():
                    if 'filament' in k.lower() or 'colour' in k.lower() or 'color' in k.lower():
                        result[f'ini_{sec_name}_{k}'] = v[:500] if len(v) > 500 else v

    # User filament preset directory
    user_dir = os.path.join(appdata, app, 'user')
    result['user_dir'] = user_dir
    result['user_dir_exists'] = os.path.isdir(user_dir)
    if os.path.isdir(user_dir):
        # List user IDs
        try:
            user_ids = os.listdir(user_dir)
            result['user_ids'] = user_ids[:5]
            for uid in user_ids[:2]:
                fil_dir = os.path.join(user_dir, uid, 'filament')
                if os.path.isdir(fil_dir):
                    try:
                        fils = os.listdir(fil_dir)
                        result[f'user_{uid}_filaments'] = fils[:20]
                        # Read first filament preset to show structure
                        if fils:
                            sample = os.path.join(fil_dir, fils[0])
                            if os.path.isfile(sample):
                                txt = _try_read_file(sample)
                                if txt:
                                    result[f'user_filament_sample_name'] = fils[0]
                                    result[f'user_filament_sample_first500'] = txt[:500]
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            pass

    # System filament presets
    sys_fil_dir = os.path.join(appdata, app, 'system', 'Bambu', 'filament')
    if not os.path.isdir(sys_fil_dir):
        # Try program files
        for pf in [os.environ.get('ProgramFiles', ''), os.environ.get('ProgramFiles(x86)', '')]:
            prog_name = 'Bambu Studio' if slicer_type != 'orca' else 'OrcaSlicer'
            d = os.path.join(pf, prog_name, 'resources', 'profiles', 'Bambu', 'filament')
            if os.path.isdir(d):
                sys_fil_dir = d
                break
    result['system_filament_dir'] = sys_fil_dir
    result['system_filament_exists'] = os.path.isdir(sys_fil_dir)

    # Temp dir (check bamboo_model, orcaslicer_model, orca_model)
    temp = tempfile.gettempdir()
    temp_dirs = ['bamboo_model']
    if slicer_type == 'orca':
        temp_dirs = ['orcaslicer_model', 'orca_model', 'bamboo_model']
    for td in temp_dirs:
        model_root = os.path.join(temp, td)
        result[f'temp_dir_{td}'] = model_root
        result[f'temp_exists_{td}'] = os.path.isdir(model_root)
        if os.path.isdir(model_root):
            all_files = []
            for rd, ds, fs in os.walk(model_root):
                for fn in fs:
                    fp = os.path.join(rd, fn)
                    rel = os.path.relpath(fp, model_root)
                    try:
                        all_files.append(f'{rel} ({os.path.getsize(fp)}B)')
                    except OSError:
                        all_files.append(rel)
            result[f'temp_files_{td}'] = all_files[:30]

    return result


def _parse_conf_ini_sections(text):
    """Extract INI [sections] from BambuStudio.conf (may follow JSON block).
    Returns dict of {section_name: {key: value, ...}}.
    """
    sections = {}
    current_section = None

    # Find where INI starts — look for [section] headers
    for line in text.splitlines():
        stripped = line.strip()
        # Skip JSON content
        if stripped.startswith('{') or stripped.startswith('}'):
            continue
        # Section header
        m = re.match(r'^\[([^\]]+)\]$', stripped)
        if m:
            current_section = m.group(1).lower()
            sections[current_section] = {}
            continue
        # Key = value in a section
        if current_section and '=' in stripped:
            idx = stripped.index('=')
            key = stripped[:idx].strip()
            val = stripped[idx+1:].strip()
            sections[current_section][key] = val

    return sections

# Embedded SVG data for icon generation
KEYCAP_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 306.06 217.55">
  <defs><style>
    .c1{stroke:#ccc;stroke-miterlimit:10;fill:none}
    .c2{fill:aqua;stroke:aqua;stroke-miterlimit:10}
    .c3{stroke:aqua;stroke-miterlimit:10;fill:none;stroke-width:4px}
    .c4{fill:#b3b3b3}
  </style></defs>
  <polygon class="c4" points="273.2 41.92 305.59 144.63 149.26 216.93 148.91 216.18 151.25 80.26 273.2 41.92"/>
  <polygon class="c4" points="273.2 41.92 151.25 80.26 35.16 29.06 152.73 .49 273.2 41.92"/>
  <polygon class="c4" points="151.25 80.26 148.91 216.18 .25 136.62 .61 135.77 35.16 29.06 151.25 80.26"/>
  <line class="c1" x1="35.16" y1="29.06" x2=".61" y2="135.77"/>
  <line class="c1" x1=".25" y1="136.62" x2="148.91" y2="216.18"/>
  <line class="c1" x1="151.25" y1="80.26" x2="35.16" y2="29.06"/>
  <line class="c1" x1="148.91" y1="216.18" x2="151.25" y2="80.26"/>
  <line class="c1" x1="273.2" y1="41.92" x2="151.25" y2="80.26"/>
  <line class="c1" x1="305.59" y1="144.63" x2="273.2" y2="41.92"/>
  <polyline class="c1" points="148.91 217.1 149.26 216.93 305.59 144.63"/>
  <line class="c1" x1="152.73" y1=".49" x2="273.2" y2="41.92"/>
  <line class="c1" x1="152.73" y1=".49" x2="35.16" y2="29.06"/>
  <line class="c3" x1="86.1" y1="30.23" x2="119.97" y2="22"/>
  <line class="c3" x1="155.68" y1="60.92" x2="86.1" y2="30.23"/>
  <line class="c3" x1="224.32" y1="40.72" x2="154.45" y2="60.92"/>
  <line class="c3" x1="224.32" y1="41.22" x2="198.07" y2="32.19"/>
  <path class="c2" d="M167.62,24.24s-20.08-4.1-28.79,0c-8.7,4.1,7.85-6.02,3.19-9.13s11.8,5.35,23.8.19c12-5.15-13.25,5.77,1.79,8.94Z"/>
  <path class="c2" d="M169.51,46.26s-18.64-3.8-26.72,0c-8.08,3.8,7.29-5.59,2.96-8.48-4.32-2.88,10.96,4.96,22.1.18,11.14-4.78-12.3,5.36,1.66,8.3Z"/>
  <path class="c2" d="M134.59,37.59s-10.53-2.15-15.09,0,4.12-3.16,1.67-4.79c-2.44-1.63,6.19,2.8,12.48.1,6.29-2.7-6.94,3.03.94,4.69Z"/>
</svg>'''


# =====================================================
# Icon Generation
# =====================================================
def create_keycap_icon(size=64):
    """Render keycap icon using PIL at any size with high quality"""
    from PIL import Image, ImageDraw

    # Render at 4x then downscale for anti-aliasing
    render_size = size * 4
    img = Image.new('RGBA', (render_size, render_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # SVG viewBox: 0 0 306.06 217.55
    # We need to fit this into a square with padding
    vw, vh = 306.06, 217.55
    padding = 0.08  # 8% padding
    usable = render_size * (1 - 2 * padding)
    scale = min(usable / vw, usable / vh)
    ox = (render_size - vw * scale) / 2
    oy = (render_size - vh * scale) / 2

    def p(x, y):
        """Transform SVG coords to pixel coords"""
        return (ox + x * scale, oy + y * scale)

    def poly(points, fill=None, outline=None, width=1):
        coords = [p(x, y) for x, y in points]
        if fill:
            draw.polygon(coords, fill=fill)
        if outline:
            for i in range(len(coords)):
                j = (i + 1) % len(coords)
                draw.line([coords[i], coords[j]], fill=outline, width=max(1, int(width * scale / 80)))

    def line(x1, y1, x2, y2, fill, width):
        w = max(1, int(width * scale / 80))
        draw.line([p(x1, y1), p(x2, y2)], fill=fill, width=w)

    # Background (dark circle for tray visibility)
    margin = int(render_size * 0.02)
    draw.ellipse([margin, margin, render_size - margin, render_size - margin],
                 fill=(26, 26, 46, 240))

    # Gray keycap faces
    gray = (179, 179, 179, 255)
    # Right face
    poly([(273.2, 41.92), (305.59, 144.63), (149.26, 216.93), (148.91, 216.18), (151.25, 80.26)], fill=(140, 140, 140, 255))
    # Top face
    poly([(273.2, 41.92), (151.25, 80.26), (35.16, 29.06), (152.73, 0.49)], fill=gray)
    # Left face
    poly([(151.25, 80.26), (148.91, 216.18), (0.25, 136.62), (0.61, 135.77), (35.16, 29.06)], fill=(120, 120, 120, 255))

    # Gray edge lines
    edge_color = (204, 204, 204, 255)
    lw = 1.0
    line(35.16, 29.06, 0.61, 135.77, edge_color, lw)
    line(0.25, 136.62, 148.91, 216.18, edge_color, lw)
    line(151.25, 80.26, 35.16, 29.06, edge_color, lw)
    line(148.91, 216.18, 151.25, 80.26, edge_color, lw)
    line(273.2, 41.92, 151.25, 80.26, edge_color, lw)
    line(305.59, 144.63, 273.2, 41.92, edge_color, lw)
    line(148.91, 217.1, 305.59, 144.63, edge_color, lw)
    line(152.73, 0.49, 273.2, 41.92, edge_color, lw)
    line(152.73, 0.49, 35.16, 29.06, edge_color, lw)

    # Cyan legend lines (thicker)
    cyan = (0, 255, 255, 255)
    lw_thick = 4.0
    line(86.1, 30.23, 119.97, 22.0, cyan, lw_thick)
    line(155.68, 60.92, 86.1, 30.23, cyan, lw_thick)
    line(224.32, 40.72, 154.45, 60.92, cyan, lw_thick)
    line(224.32, 41.22, 198.07, 32.19, cyan, lw_thick)

    # Cyan decorative shapes (simplified as ellipses/ovals on the top face)
    # Large shape around (150, 24)
    cx1, cy1 = p(150, 20)
    rx1 = 30 * scale / 80
    ry1 = 8 * scale / 80
    draw.ellipse([cx1 - rx1, cy1 - ry1, cx1 + rx1, cy1 + ry1], fill=cyan)

    # Medium shape around (152, 44)
    cx2, cy2 = p(152, 43)
    rx2 = 26 * scale / 80
    ry2 = 7 * scale / 80
    draw.ellipse([cx2 - rx2, cy2 - ry2, cx2 + rx2, cy2 + ry2], fill=cyan)

    # Small shape around (127, 36)
    cx3, cy3 = p(127, 36)
    rx3 = 15 * scale / 80
    ry3 = 5 * scale / 80
    draw.ellipse([cx3 - rx3, cy3 - ry3, cx3 + rx3, cy3 + ry3], fill=cyan)

    # Downscale with high-quality resampling
    img = img.resize((size, size), Image.LANCZOS)
    return img


def create_keycap_icon_from_svg(size=64):
    """Try to use cairosvg for perfect SVG rendering, fallback to PIL"""
    try:
        import cairosvg
        from PIL import Image
        import io
        png_data = cairosvg.svg2png(bytestring=KEYCAP_SVG.encode(), output_width=size, output_height=size)
        # Add dark circle background for tray visibility
        svg_img = Image.open(io.BytesIO(png_data)).convert('RGBA')
        bg = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw_bg = __import__('PIL.ImageDraw', fromlist=['ImageDraw']).Draw(bg)
        m = max(1, size // 32)
        draw_bg.ellipse([m, m, size - m, size - m], fill=(26, 26, 46, 240))
        # Paste SVG on top with padding
        pad = int(size * 0.1)
        svg_resized = svg_img.resize((size - 2 * pad, size - 2 * pad), Image.LANCZOS)
        bg.paste(svg_resized, (pad, pad + int(size * 0.05)), svg_resized)
        return bg
    except Exception:
        return create_keycap_icon(size)


def create_icon_file(path, sizes=None):
    """Create .ico file with multiple sizes"""
    from PIL import Image
    if sizes is None:
        sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [create_keycap_icon_from_svg(sz) for sz in sizes]
    images[0].save(path, format='ICO', sizes=[(s, s) for s in sizes], append_images=images[1:])
    return path


# =====================================================
# Windows API helpers (thread-safe message boxes)
# =====================================================
def win_msgbox(text, title, flags=0):
    """Thread-safe Windows MessageBox using ctypes"""
    try:
        import ctypes
        MB_OK = 0x00
        MB_YESNO = 0x04
        MB_ICONINFO = 0x40
        MB_ICONWARNING = 0x30
        MB_ICONERROR = 0x10
        IDYES = 6
        result = ctypes.windll.user32.MessageBoxW(0, text, title, flags)
        return result
    except Exception:
        print(f"[MsgBox] {title}: {text}")
        return 0


def win_yesno(text, title):
    """Thread-safe Yes/No dialog, returns True if Yes"""
    try:
        import ctypes
        MB_YESNO = 0x04
        MB_ICONWARNING = 0x30
        IDYES = 6
        result = ctypes.windll.user32.MessageBoxW(0, text, title, MB_YESNO | MB_ICONWARNING)
        return result == IDYES
    except Exception:
        return False


def win_info(text, title):
    """Thread-safe info dialog"""
    try:
        import ctypes
        MB_OK = 0x00
        MB_ICONINFO = 0x40
        ctypes.windll.user32.MessageBoxW(0, text, title, MB_OK | MB_ICONINFO)
    except Exception:
        print(f"[Info] {title}: {text}")


# =====================================================
# Registry / Autostart
# =====================================================
def get_exe_path():
    if getattr(sys, 'frozen', False):
        return sys.executable
    return os.path.abspath(__file__)


def is_autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, REG_VALUE_NAME)
            return True
    except Exception:
        return False


def set_autostart(enable):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
            if enable:
                exe = get_exe_path()
                winreg.SetValueEx(key, REG_VALUE_NAME, 0, winreg.REG_SZ, f'"{exe}" --silent')
            else:
                try:
                    winreg.DeleteValue(key, REG_VALUE_NAME)
                except FileNotFoundError:
                    pass
            return True
    except Exception as e:
        print(f"[Autostart] Error: {e}")
        return False


# =====================================================
# Config
# =====================================================
def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {"installed": False, "autostart": False}


def save_config(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"[Config] Save error: {e}")


# =====================================================
# Installer UI (tkinter)
# =====================================================
def show_installer():
    """Show installer dialog"""
    import tkinter as tk
    from PIL import ImageTk

    result = {"action": None, "autostart": True}

    WIN_W, WIN_H = 540, 560

    root = tk.Tk()
    root.title(f"{APP_NAME} - Setup")
    root.geometry(f"{WIN_W}x{WIN_H}")
    root.resizable(False, False)
    root.configure(bg="#1a1a2e")

    # Set titlebar icon
    try:
        ico_img = create_keycap_icon_from_svg(32)
        _tk_icon = ImageTk.PhotoImage(ico_img)
        root.iconphoto(True, _tk_icon)
    except Exception:
        pass

    # Center on screen
    root.update_idletasks()
    x = (root.winfo_screenwidth() - WIN_W) // 2
    y = (root.winfo_screenheight() - WIN_H) // 2
    root.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")

    # Icon area - use PIL rendered icon instead of emoji
    try:
        header_img = create_keycap_icon_from_svg(72)
        _tk_header = ImageTk.PhotoImage(header_img)
        tk.Label(root, image=_tk_header, bg="#1a1a2e").pack(pady=(20, 4))
        root._keep_header = _tk_header  # prevent GC
    except Exception:
        tk.Label(root, text="⌨", font=("Segoe UI Emoji", 36),
                 bg="#1a1a2e", fg="#00ffff").pack(pady=(20, 4))

    tk.Label(root, text=APP_NAME, font=("Segoe UI", 18, "bold"),
             bg="#1a1a2e", fg="#ffffff").pack()
    tk.Label(root, text=f"Version {VERSION}", font=("Segoe UI", 9),
             bg="#1a1a2e", fg="#888888").pack(pady=(2, 0))

    # Description
    desc = (
        "Keycap Generator のブラウザから\n"
        "Bambu Studio / OrcaSlicer へ\n"
        "モデルを直接転送するブリッジアプリです。"
    )
    tk.Label(root, text=desc, font=("Segoe UI", 10), bg="#1a1a2e", fg="#cccccc",
             justify="center").pack(pady=(12, 8))

    # Install location
    loc_frame = tk.Frame(root, bg="#1a1a2e")
    loc_frame.pack(fill="x", padx=40, pady=(4, 0))
    tk.Label(loc_frame, text="インストール先:", font=("Segoe UI", 9),
             bg="#1a1a2e", fg="#999999", anchor="w").pack(anchor="w")
    tk.Label(loc_frame, text=INSTALL_DIR, font=("Segoe UI", 8),
             bg="#222244", fg="#4fc3f7", relief="flat", padx=8, pady=3,
             anchor="w", wraplength=450).pack(fill="x", pady=(2, 0))

    # Autostart checkbox
    autostart_var = tk.BooleanVar(value=True)
    cb = tk.Checkbutton(root, text="  Windows 起動時に自動起動する",
                        variable=autostart_var,
                        font=("Segoe UI", 10), bg="#1a1a2e", fg="#cccccc",
                        selectcolor="#2a2a4e", activebackground="#1a1a2e",
                        activeforeground="#cccccc", anchor="w")
    cb.pack(pady=(10, 6))

    # Slicer detection
    det_frame = tk.Frame(root, bg="#1e1e38", relief="flat", bd=0)
    det_frame.pack(fill="x", padx=40, pady=(4, 0))
    tk.Label(det_frame, text="スライサー検出状況", font=("Segoe UI", 9, "bold"),
             bg="#1e1e38", fg="#999999").pack(anchor="w", padx=10, pady=(6, 2))
    for name, stype in [("Bambu Studio", "bambu"), ("OrcaSlicer", "orca")]:
        path = find_slicer(stype)
        if path:
            status_text = f"  ✓  {name} — 検出済み"
            color = "#4caf50"
        else:
            status_text = f"  ✗  {name} — 未検出"
            color = "#f44336"
        tk.Label(det_frame, text=status_text, font=("Segoe UI", 9),
                 bg="#1e1e38", fg=color, anchor="w").pack(anchor="w", padx=10, pady=1)
    tk.Label(det_frame, text="", bg="#1e1e38", font=("Segoe UI", 1)).pack(pady=(0, 4))

    # Buttons
    btn_frame = tk.Frame(root, bg="#1a1a2e")
    btn_frame.pack(pady=(18, 12))

    def on_install():
        result["action"] = "install"
        result["autostart"] = autostart_var.get()
        root.destroy()

    def on_cancel():
        result["action"] = "cancel"
        root.destroy()

    install_btn = tk.Button(btn_frame, text="  インストール  ", command=on_install,
                            font=("Segoe UI", 12, "bold"), bg="#4fc3f7", fg="#000000",
                            relief="flat", padx=20, pady=7, cursor="hand2")
    install_btn.pack(side="left", padx=10)

    cancel_btn = tk.Button(btn_frame, text="  キャンセル  ", command=on_cancel,
                           font=("Segoe UI", 12), bg="#444444", fg="#cccccc",
                           relief="flat", padx=14, pady=7, cursor="hand2")
    cancel_btn.pack(side="left", padx=10)

    root.mainloop()
    return result


def do_install(autostart=True):
    try:
        os.makedirs(INSTALL_DIR, exist_ok=True)

        src = get_exe_path()
        if getattr(sys, 'frozen', False):
            dst = os.path.join(INSTALL_DIR, os.path.basename(src))
            if os.path.abspath(src).lower() != os.path.abspath(dst).lower():
                shutil.copy2(src, dst)

        try:
            create_icon_file(os.path.join(INSTALL_DIR, "icon.ico"))
        except Exception as e:
            print(f"[Install] Icon error: {e}")

        if autostart:
            set_autostart(True)

        config = load_config()
        config["installed"] = True
        config["autostart"] = autostart
        save_config(config)

        try:
            create_shortcut()
        except Exception as e:
            print(f"[Install] Shortcut error: {e}")

        print(f"[Install] Installed to {INSTALL_DIR}")
        return True
    except Exception as e:
        print(f"[Install] Error: {e}")
        return False


def create_shortcut():
    try:
        start_menu = os.path.join(os.environ.get('APPDATA', ''),
                                   'Microsoft', 'Windows', 'Start Menu', 'Programs')
        shortcut_path = os.path.join(start_menu, f"{APP_NAME}.lnk")
        exe_path = get_exe_path()
        if getattr(sys, 'frozen', False):
            exe_path = os.path.join(INSTALL_DIR, os.path.basename(exe_path))
        ico_path = os.path.join(INSTALL_DIR, "icon.ico")

        ps_cmd = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{shortcut_path}"); '
            f'$s.TargetPath = "{exe_path}"; '
            f'$s.Arguments = "--silent"; '
            f'$s.WorkingDirectory = "{INSTALL_DIR}"; '
            f'$s.Description = "{APP_NAME}"; '
            f'if (Test-Path "{ico_path}") {{ $s.IconLocation = "{ico_path}" }}; '
            f'$s.Save()'
        )
        subprocess.run(['powershell', '-Command', ps_cmd],
                       capture_output=True, timeout=10,
                       creationflags=0x08000000 if sys.platform == 'win32' else 0)
    except Exception as e:
        print(f"[Shortcut] Error: {e}")


# =====================================================
# Uninstaller
# =====================================================
def do_uninstall():
    try:
        set_autostart(False)

        # Remove shortcut
        start_menu = os.path.join(os.environ.get('APPDATA', ''),
                                   'Microsoft', 'Windows', 'Start Menu', 'Programs')
        shortcut_path = os.path.join(start_menu, f"{APP_NAME}.lnk")
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)

        # Remove temp
        if os.path.exists(TEMP_DIR):
            shutil.rmtree(TEMP_DIR, ignore_errors=True)

        # Schedule self-deletion
        bat_content = (
            '@echo off\n'
            'timeout /t 3 /nobreak >nul\n'
            f'rmdir /s /q "{INSTALL_DIR}"\n'
            'del "%~f0"\n'
        )
        bat_path = os.path.join(tempfile.gettempdir(), "uninstall_ksb.bat")
        with open(bat_path, 'w') as f:
            f.write(bat_content)

        subprocess.Popen(
            ['cmd', '/c', bat_path],
            creationflags=0x08000000 if sys.platform == 'win32' else 0
        )

        win_info(
            f"{APP_NAME} をアンインストールしました。\nアプリを終了します。",
            APP_NAME
        )
        return True
    except Exception as e:
        print(f"[Uninstall] Error: {e}")
        return False


# =====================================================
# Slicer Detection
# =====================================================
def find_slicer(slicer_type):
    paths = SLICER_PATHS.get(slicer_type, [])
    for p in paths:
        if os.path.isfile(p):
            return p
    try:
        import winreg
        reg_keys = []
        if slicer_type == "bambu":
            reg_keys = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Bambu Studio"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Bambu Studio"),
                (winreg.HKEY_CLASSES_ROOT, r"bambustudio\shell\open\command"),
            ]
        else:
            reg_keys = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\OrcaSlicer"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\OrcaSlicer"),
                (winreg.HKEY_CLASSES_ROOT, r"orcaslicer\shell\open\command"),
            ]
        for hive, key_path in reg_keys:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    exe_path = val.strip('"').split('"')[0]
                    if os.path.isfile(exe_path):
                        return exe_path
            except (FileNotFoundError, OSError):
                continue
    except Exception:
        pass
    exe_name = "bambu-studio.exe" if slicer_type == "bambu" else "orca-slicer.exe"
    return shutil.which(exe_name)


def is_origin_allowed(origin):
    if not origin:
        return True
    return any(origin.startswith(a) for a in ALLOWED_ORIGINS)


# =====================================================
# HTTP Server
# =====================================================
class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _set_cors_headers(self):
        origin = self.headers.get('Origin', '')
        if is_origin_allowed(origin):
            self.send_header('Access-Control-Allow-Origin', origin if origin else '*')
        else:
            self.send_header('Access-Control-Allow-Origin', 'null')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Max-Age', '86400')

    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/health':
            bambu = find_slicer("bambu")
            orca = find_slicer("orca")
            self._send_json(200, {
                "status": "ok", "version": VERSION, "app": APP_NAME,
                "slicers": {
                    "bambu": {"available": bambu is not None, "path": bambu or ""},
                    "orca": {"available": orca is not None, "path": orca or ""},
                },
                "features": ["project-filaments"]
            })
        elif self.path.startswith('/project-filaments'):
            slicer = 'bambu'
            if '?' in self.path:
                from urllib.parse import parse_qs, urlparse
                qs = parse_qs(urlparse(self.path).query)
                slicer = qs.get('slicer', ['bambu'])[0]
            try:
                result = get_project_filaments(slicer)
                self._send_json(200, result)
            except Exception as e:
                import traceback
                self._send_json(500, {"error": str(e), "tb": traceback.format_exc()})
        elif self.path.startswith('/debug'):
            slicer = 'bambu'
            if '?' in self.path:
                from urllib.parse import parse_qs, urlparse
                qs = parse_qs(urlparse(self.path).query)
                slicer = qs.get('slicer', ['bambu'])[0]
            try:
                result = debug_slicer_conf(slicer)
                self._send_json(200, result)
            except Exception as e:
                import traceback
                self._send_json(500, {"error": str(e), "tb": traceback.format_exc()})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        origin = self.headers.get('Origin', '')
        if not is_origin_allowed(origin):
            self._send_json(403, {"error": "Origin not allowed"})
            return
        if self.path != '/open':
            self._send_json(404, {"error": "Not found"})
            return
        try:
            content_type = self.headers.get('Content-Type', '')
            if 'multipart/form-data' not in content_type:
                self._send_json(400, {"error": "Expected multipart/form-data"})
                return

            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            # Parse multipart boundary
            boundary = None
            for part in content_type.split(';'):
                part = part.strip()
                if part.startswith('boundary='):
                    boundary = part[9:].strip('"')
                    break
            if not boundary:
                self._send_json(400, {"error": "No boundary in multipart"})
                return

            # Parse multipart fields
            slicer_type = 'bambu'
            file_data = None
            filename = 'model.3mf'
            boundary_bytes = ('--' + boundary).encode()
            parts = body.split(boundary_bytes)
            for part in parts:
                if b'Content-Disposition' not in part:
                    continue
                header_end = part.find(b'\r\n\r\n')
                if header_end < 0:
                    continue
                header_section = part[:header_end].decode('utf-8', errors='replace')
                part_body = part[header_end + 4:]
                if part_body.endswith(b'\r\n'):
                    part_body = part_body[:-2]

                # Extract field name
                name_match = re.search(r'name="([^"]*)"', header_section)
                if not name_match:
                    continue
                field_name = name_match.group(1)

                if field_name == 'slicer':
                    slicer_type = part_body.decode('utf-8', errors='replace').strip().lower()
                elif field_name == 'file':
                    file_data = part_body
                    fn_match = re.search(r'filename="([^"]*)"', header_section)
                    if fn_match and fn_match.group(1):
                        filename = os.path.basename(fn_match.group(1))

            slicer_type = slicer_type if slicer_type in ('bambu', 'orca') else 'bambu'

            slicer_path = find_slicer(slicer_type)
            if not slicer_path:
                name = "Bambu Studio" if slicer_type == "bambu" else "OrcaSlicer"
                self._send_json(404, {"error": f"{name} not found",
                                       "message": f"{name}が見つかりません。"})
                return

            if file_data is None:
                self._send_json(400, {"error": "No file provided"})
                return

            _, ext = os.path.splitext(filename)
            if ext.lower() not in ALLOWED_EXTENSIONS:
                self._send_json(400, {"error": f"File type not allowed: {ext}"})
                return

            if len(file_data) > 100 * 1024 * 1024:
                self._send_json(400, {"error": "File too large (max 100MB)"})
                return

            os.makedirs(TEMP_DIR, exist_ok=True)
            file_path = os.path.join(TEMP_DIR, filename)

            with open(file_path, 'wb') as f:
                f.write(file_data)

            subprocess.Popen([slicer_path, file_path])
            name = "Bambu Studio" if slicer_type == "bambu" else "OrcaSlicer"
            self._send_json(200, {
                "success": True,
                "message": f"{name}でモデルを開きました",
                "slicer": name, "file": filename
            })
        except Exception as e:
            self._send_json(500, {"error": "Internal error", "detail": str(e)})


def run_server():
    HTTPServer(('127.0.0.1', PORT), BridgeHandler).serve_forever()


# =====================================================
# System Tray
# =====================================================
def create_tray_icon():
    try:
        import pystray

        icon_img = create_keycap_icon_from_svg(64)

        def on_healthcheck(icon, item):
            import webbrowser
            webbrowser.open(f"http://localhost:{PORT}/health")

        def on_toggle_autostart(icon, item):
            new_state = not is_autostart_enabled()
            if set_autostart(new_state):
                config = load_config()
                config["autostart"] = new_state
                save_config(config)
                icon.update_menu()

        def autostart_checked(item):
            return is_autostart_enabled()

        def on_uninstall(icon, item):
            # Run in separate thread to avoid pystray blocking
            def _do():
                import ctypes
                MB_YESNO = 0x04
                MB_ICONWARNING = 0x30
                MB_TOPMOST = 0x40000
                IDYES = 6
                result = ctypes.windll.user32.MessageBoxW(
                    0,
                    f"{APP_NAME} をアンインストールしますか？\n\n"
                    f"以下が削除されます:\n"
                    f"  • インストールフォルダ\n"
                    f"  • 自動起動設定\n"
                    f"  • スタートメニューのショートカット",
                    f"{APP_NAME} - アンインストール",
                    MB_YESNO | MB_ICONWARNING | MB_TOPMOST
                )
                if result == IDYES:
                    icon.stop()
                    do_uninstall()
                    os._exit(0)
            threading.Thread(target=_do, daemon=True).start()

        def on_quit(icon, item):
            icon.stop()
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem(f"{APP_NAME} v{VERSION}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("ヘルスチェック", on_healthcheck),
            pystray.MenuItem("Windows起動時に自動起動",
                             on_toggle_autostart, checked=autostart_checked),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("アンインストール", on_uninstall),
            pystray.MenuItem("終了", on_quit),
        )

        return pystray.Icon(APP_NAME, icon_img, f"{APP_NAME} - Port {PORT}", menu)
    except Exception as e:
        print(f"[{APP_NAME}] Tray icon failed: {e}")
        return None


# =====================================================
# Main
# =====================================================
def main():
    silent = '--silent' in sys.argv
    config = load_config()

    # First run installer
    if not config.get("installed") and not silent:
        result = show_installer()
        if result["action"] == "install":
            if do_install(autostart=result.get("autostart", True)):
                config = load_config()
                win_info(
                    f"{APP_NAME} をインストールしました！\n\n"
                    f"タスクトレイに常駐します。\n"
                    f"アイコンを右クリックでメニューを表示できます。",
                    APP_NAME
                )
            else:
                win_info("インストールに失敗しました。", APP_NAME)
                sys.exit(1)
        elif result["action"] != "cancel":
            sys.exit(0)

    # Banner
    if not silent:
        print(f"{'=' * 50}")
        print(f"  {APP_NAME} v{VERSION}")
        print(f"  http://127.0.0.1:{PORT}")
        print(f"{'=' * 50}")
        for name, stype in [("Bambu Studio", "bambu"), ("OrcaSlicer", "orca")]:
            path = find_slicer(stype)
            mark = "✓" if path else "✗"
            print(f"  {mark} {name}: {path or 'not found'}")
        print()

    os.makedirs(TEMP_DIR, exist_ok=True)

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    if not silent:
        print(f"  Server started on port {PORT}")

    icon = create_tray_icon()
    if icon:
        if not silent:
            print(f"  Tray icon active")
        icon.run()
    else:
        if not silent:
            print(f"  Console mode (Ctrl+C to quit)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == '__main__':
    main()
