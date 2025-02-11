from flask import Flask, request, jsonify
import yaml
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Load kubeconfig dari lokasi default (~/.kube/config)
config.load_kube_config()

@app.route('/deploy', methods=['POST'])
def deploy():
    data = request.json
    yaml_content = data.get('yamlContent')

    if not yaml_content:
        return jsonify({'status': 'error', 'message': 'YAML content is required'}), 400

    try:
        yaml_data = yaml.safe_load(yaml_content)

        if not isinstance(yaml_data, dict):
            return jsonify({'status': 'error', 'message': 'Invalid YAML structure'}), 400

        if yaml_data.get('kind') == 'Deployment':
            api_instance = client.AppsV1Api()
            api_instance.create_namespaced_deployment(
                body=yaml_data,
                namespace='test'
            )
        elif yaml_data.get('kind') == 'Service':
            api_instance = client.CoreV1Api()
            api_instance.create_namespaced_service(
                body=yaml_data,
                namespace='test'
            )
        elif yaml_data.get('kind') == 'ConfigMap':
            api_instance = client.CoreV1Api()
            api_instance.create_namespaced_config_map(
                body=yaml_data,
                namespace='test'
            )
        else:
            return jsonify({'status': 'error', 'message': 'Unsupported resource type'}), 400

        return jsonify({
            'status': 'success',
            'message': 'Resource created successfully'
        })
    except ApiException as e:
        error_message = e.body if hasattr(e, 'body') else str(e)
        return jsonify({
            'status': 'error',
            'message': f'Kubernetes API error: {error_message}'
        }), 500
    except yaml.YAMLError as e:
        return jsonify({
            'status': 'error',
            'message': f'Invalid YAML: {str(e)}'
        }), 400
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'An error occurred: {str(e)}'
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
