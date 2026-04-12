#!/usr/bin/env python3
"""
Script para parchear IQOptionAPI y corregir problemas de compatibilidad con websocket-client
"""

import os
import sys
import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def find_iqapi_files():
    """Encuentra los archivos de IQOptionAPI que necesitan parches"""
    files_to_patch = []
    
    # Buscar en los directorios comunes donde se instalan los paquetes
    search_paths = [
        '/opt/render/project/src',
        os.path.join(os.path.dirname(sys.executable), '..', 'lib'),
        '/usr/local/lib/python3.10/site-packages',
        '/opt/render/project/src/.venv/lib/python3.10/site-packages'
    ]
    
    for search_path in search_paths:
        if os.path.exists(search_path):
            for root, dirs, files in os.walk(search_path):
                if 'iqoptionapi' in root.lower():
                    for file in files:
                        if file == 'client.py' and 'ws' in root:
                            files_to_patch.append(os.path.join(root, file))
                            logger.info(f"Encontrado archivo a parchear: {os.path.join(root, file)}")
    
    return files_to_patch

def patch_websocket_client(file_path):
    """Aplica el parche al archivo client.py de IQOptionAPI"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Parche 1: Corregir la función on_message
        if 'def on_message(self, message):' in content:
            content = content.replace(
                'def on_message(self, message):',
                'def on_message(self, ws, message):'
            )
            logger.info(f"Aplicado parche on_message en {file_path}")
        
        # Parche 2: Corregir on_error si existe
        if 'def on_error(self, error):' in content:
            content = content.replace(
                'def on_error(self, error):',
                'def on_error(self, ws, error):'
            )
            logger.info(f"Aplicado parche on_error en {file_path}")
        
        # Parche 3: Corregir on_close si existe
        if 'def on_close(self):' in content:
            content = content.replace(
                'def on_close(self):',
                'def on_close(self, ws, close_status_code=None, close_msg=None):'
            )
            logger.info(f"Aplicado parche on_close en {file_path}")
        
        # Parche 4: Corregir on_open si existe
        if 'def on_open(self):' in content:
            content = content.replace(
                'def on_open(self):',
                'def on_open(self, ws):'
            )
            logger.info(f"Aplicado parche on_open en {file_path}")
        
        # Solo escribir si hubo cambios
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"✅ Parches aplicados exitosamente en {file_path}")
            return True
        else:
            logger.info(f"✅ No se necesitaron parches en {file_path}")
            return True
            
    except Exception as e:
        logger.error(f"❌ Error aplicando parche en {file_path}: {e}")
        return False

def main():
    """Función principal"""
    logger.info("🔧 Iniciando parcheo de IQOptionAPI...")
    
    files_to_patch = find_iqapi_files()
    
    if not files_to_patch:
        logger.warning("⚠️ No se encontraron archivos de IQOptionAPI para parchear")
        logger.info("Esto puede ser normal si el paquete no está instalado aún")
        return True
    
    success_count = 0
    for file_path in files_to_patch:
        if patch_websocket_client(file_path):
            success_count += 1
    
    if success_count == len(files_to_patch):
        logger.info(f"✅ Todos los archivos parcheados exitosamente ({success_count}/{len(files_to_patch)})")
        return True
    else:
        logger.error(f"❌ Algunos archivos no pudieron ser parcheados ({success_count}/{len(files_to_patch)})")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
