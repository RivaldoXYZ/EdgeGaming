from flask import Flask, request, jsonify
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from flask_cors import CORS
import random
import string
import re
import time

app = Flask(__name__)
CORS(app)

config.load_kube_config()

core_api = client.CoreV1Api()
apps_api = client.AppsV1Api()

NFS_CONFIG = {
    'storage_class': 'openebs-hostpath'
}

ALLOWED_PACKAGES = {
    'small':   {'cpu': 6000,  'mem': 24576,  'storage_home': 50, 'storage_games': 400},
    'medium':  {'cpu': 8000,  'mem': 32768,  'storage_home': 100, 'storage_games': 800},
    'large':   {'cpu': 12000, 'mem': 49152,  'storage_home': 200, 'storage_games': 1600}
}

credentials_store = {}

def generate_deployment_name():
    return 'steam-' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))

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

        pvcs = [
            {
                'apiVersion': 'v1',
                'kind': 'PersistentVolumeClaim',
                'metadata': {'name': f'{deployment_name}-games'},
                'spec': {
                    'storageClassName': NFS_CONFIG['storage_class'],
                    'volumeMode': 'Filesystem',
                    'resources': {'requests': {'storage': f'{resources["storage_games"]}Gi'}},
                    'accessModes': ['ReadWriteOnce']
                }
            },
            {
                'apiVersion': 'v1',
                'kind': 'PersistentVolumeClaim',
                'metadata': {'name': f'{deployment_name}-home'},
                'spec': {
                    'storageClassName': NFS_CONFIG['storage_class'],
                    'volumeMode': 'Filesystem',
                    'resources': {'requests': {'storage': f'{resources["storage_home"]}Gi'}},
                    'accessModes': ['ReadWriteOnce']
                }
            }
        ]
        
        for pvc in pvcs:
            core_api.create_namespaced_persistent_volume_claim(namespace='default', body=pvc)

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
                                'requests': {'cpu': f'{resources["cpu"]}m', 'memory': f'{resources["mem"]}Mi'},
                                'limits': {'cpu': f'{resources["cpu"]}m', 'memory': f'{resources["mem"]}Mi', 'nvidia.com/gpu.shared': 1}
                            },
                            'volumeMounts': [
                                {'name': 'home-dir', 'mountPath': '/home/default/'},
                                {'name': 'games-dir', 'mountPath': '/mnt/games/'},
                                {'name': 'input-devices', 'mountPath': '/dev/input/'},
                                {'name': 'dshm', 'mountPath': '/dev/shm'}
                            ],
                            'env': [
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

@app.route('/get_credentials/<deployment_name>', methods=['GET'])
def get_credentials(deployment_name):
    creds = credentials_store.get(deployment_name)
    if not creds:
        return jsonify({'status': 'error', 'message': 'Deployment not found or credentials not available'}), 404
    return jsonify({'status': 'success', 'credentials': creds})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
