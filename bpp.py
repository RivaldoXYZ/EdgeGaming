from flask import Flask, request, jsonify, Response, stream_with_context
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from flask_cors import CORS
import random
import string
import requests

app = Flask(__name__)
CORS(app)

config.load_kube_config()

core_api = client.CoreV1Api()
apps_api = client.AppsV1Api()

NFS_CONFIG = {
    'storage_class': 'openebs-hostpath'
}

ALLOWED_PACKAGES = {
    'small':   {'cpu': 6,  'mem': 24576,  'storage_home': 50, 'storage_games': 400},
    'medium':  {'cpu': 8,  'mem': 32768,  'storage_home': 100, 'storage_games': 800},
    'large':   {'cpu': 12, 'mem': 49152,  'storage_home': 200, 'storage_games': 1600}
}

credentials_store = {}

def generate_deployment_name():
    return 'steam-' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))

def validate_credentials(deployment_name, username, password):
    creds = credentials_store.get(deployment_name)
    return creds and creds['username'] == username and creds['password'] == password

@app.route('/deploy', methods=['POST'])
def deploy():
    data = request.json
    try:
        package = data['package']
        if package not in ALLOWED_PACKAGES:
            raise ValueError("Pilih paket yang valid dari daftar yang tersedia!")
        
        resources = ALLOWED_PACKAGES[package]
        deployment_name = generate_deployment_name()

        username = 'user-' + ''.join(random.choices(string.ascii_lowercase, k=5))
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        credentials_store[deployment_name] = {'username': username, 'password': password}

        # PVC Definitions
        pvc_home = {
            'apiVersion': 'v1',
            'kind': 'PersistentVolumeClaim',
            'metadata': {'name': f'{deployment_name}-home'},
            'spec': {
                'storageClassName': NFS_CONFIG['storage_class'],
                'accessModes': ['ReadWriteOnce'],
                'resources': {'requests': {'storage': f"{resources['storage_home']}Gi"}}
            }
        }

        pvc_games = {
            'apiVersion': 'v1',
            'kind': 'PersistentVolumeClaim',
            'metadata': {'name': f'{deployment_name}-games'},
            'spec': {
                'storageClassName': NFS_CONFIG['storage_class'],
                'accessModes': ['ReadWriteOnce'],
                'resources': {'requests': {'storage': f"{resources['storage_games']}Gi"}}
            }
        }

        core_api.create_namespaced_persistent_volume_claim(namespace='default', body=pvc_home)
        core_api.create_namespaced_persistent_volume_claim(namespace='default', body=pvc_games)

        stateful_set = {
            'apiVersion': 'apps/v1',
            'kind': 'StatefulSet',
            'metadata': {'name': deployment_name},
            'spec': {
                'serviceName': deployment_name,
                'replicas': 1,
                'selector': {'matchLabels': {'app': deployment_name}},
                'template': {
                    'metadata': {'labels': {'app': deployment_name}},
                    'spec': {
                        'hostNetwork': True,
                        'securityContext': {'fsGroup': 1000},
                        'containers': [{
                            'name': 'steam-headless',
                            'securityContext': {'privileged': True},
                            'image': 'josh5/steam-headless:latest',
                            'resources': {
                                'requests': {'memory': f"{resources['mem']}Mi", 'cpu': str(resources['cpu'])},
                                'limits': {'memory': f"{resources['mem']}Mi", 'cpu': str(resources['cpu'])}
                            },
                            'volumeMounts': [
                                {'name': 'home-dir', 'mountPath': '/home/default/'},
                                {'name': 'games-dir', 'mountPath': '/mnt/games/'},
                                {'name': 'input-devices', 'mountPath': '/dev/input/'},
                                {'name': 'dshm', 'mountPath': '/dev/shm'}
                            ],
                            'env': [
                                {'name': 'NAME', 'value': 'SteamHeadless'},
                                {'name': 'TZ', 'value': 'America/New_York'},
                                {'name': 'USER_LOCALES', 'value': 'en_US.UTF-8 UTF-8'},
                                {'name': 'DISPLAY', 'value': ':55'},
                                {'name': 'SHM_SIZE', 'value': '2G'},
                                {'name': 'DOCKER_RUNTIME', 'value': 'nvidia'},
                                {'name': 'PUID', 'value': '1000'},
                                {'name': 'PGID', 'value': '1000'},
                                {'name': 'UMASK', 'value': '000'},
                                {'name': 'USER_PASSWORD', 'value': password},
                                {'name': 'MODE', 'value': 'primary'},
                                {'name': 'WEB_UI_MODE', 'value': 'vnc'},
                                {'name': 'ENABLE_VNC_AUDIO', 'value': 'false'},
                                {'name': 'PORT_NOVNC_WEB', 'value': '8083'},
                                {'name': 'ENABLE_SUNSHINE', 'value': 'true'},
                                {'name': 'SUNSHINE_USER', 'value': username},
                                {'name': 'SUNSHINE_PASS', 'value': password}
                            ],
                            'ports': [{'containerPort': 8083, 'hostPort': 8083, 'protocol': 'TCP'}]
                        }],
                        'volumes': [
                            {'name': 'home-dir', 'persistentVolumeClaim': {'claimName': f'{deployment_name}-home'}},
                            {'name': 'games-dir', 'persistentVolumeClaim': {'claimName': f'{deployment_name}-games'}},
                            {'name': 'input-devices', 'hostPath': {'path': '/dev/input/'}},
                            {'name': 'dshm', 'emptyDir': {'medium': 'Memory'}}
                        ]
                    }
                }
            }
        }
        
        apps_api.create_namespaced_stateful_set(namespace='default', body=stateful_set)
        
        return jsonify({'status': 'success', 'deployment_name': deployment_name, 'credentials': credentials_store[deployment_name]})
    
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    except ApiException as e:
        return jsonify({'status': 'error', 'message': f'Kubernetes API Error: {e.reason}'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'System Error: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
