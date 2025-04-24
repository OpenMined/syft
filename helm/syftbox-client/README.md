# SyftBox Client Helm Chart

A Helm chart for deploying SyftBox clients on Kubernetes, connecting to an existing SyftBox server.

## Overview

This chart deploys a SyftBox client that connects to a pre-existing SyftBox server. The client can be deployed using either a Deployment or StatefulSet based on your requirements.

## Prerequisites

- Kubernetes 1.16+
- Helm 3.0+
- An existing SyftBox server deployment with a known service endpoint

## Installation

```bash
# Create a namespace for SyftBox clients (optional)
kubectl create namespace syftbox-clients

# Install the chart with default values
helm install my-client ./syftbox-client --namespace syftbox-clients

# Install with custom values file
helm install my-client ./syftbox-client -f values.yaml --namespace syftbox-clients

# Install with specific overrides
helm install my-client ./syftbox-client --set client.server.url=http://my-server.example.com:8000 --set client.email=custom@openmined.org
```

## Configuration

### Server Reference

The SyftBox client needs to reference the server. You can specify this in two ways:

1. **Full URL** (recommended):
   ```yaml
   client:
     server:
       url: "http://syftbox-server.syftbox-system.svc.cluster.local:8000"
   ```

2. **Host and port separately**:
   ```yaml
   client:
     server:
       host: "syftbox-server.syftbox-system.svc.cluster.local"
       port: 8000
   ```

### Deployment Types

You can choose between two deployment types:

1. **Deployment** (default):
   ```yaml
   deploymentType: "deployment"
   ```
   
   Good for simple deployments where you don't need stable network identities.

2. **StatefulSet**:
   ```yaml
   deploymentType: "statefulset"
   ```
   
   Better for production use cases where you want stable storage and network identity.

### Client Configuration

Configure the client identity and settings:

```yaml
client:
  email: "client@openmined.org"
  config:
    client_id: "syftbox-client"
    log_level: "info"
    # Add other configuration options here
```

### Persistence Configuration

Configure persistent storage:

```yaml
persistence:
  enabled: true
  storageClass: "standard"  # Use your preferred storage class
  size: 2Gi
```

### Resources

Set resource requests and limits:

```yaml
resources:
  limits:
    cpu: 1000m
    memory: 1Gi
  requests:
    cpu: 500m
    memory: 512Mi
```

## Key Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `deploymentType` | Type of deployment (`deployment` or `statefulset`) | `deployment` |
| `client.server.url` | URL of the SyftBox server | `http://syftbox-server:8000` |
| `client.server.host` | Hostname of the server (used if url not set) | `""` |
| `client.server.port` | Port of the server (used if url not set) | `8000` |
| `client.email` | Client email identity | `client@openmined.org` |
| `client.configPath` | Configuration path inside container | `/config/syftbox/config.json` |
| `client.config` | Configuration file content | See values.yaml |
| `persistence.enabled` | Enable persistent storage | `true` |
| `persistence.size` | Size of persistent volume | `2Gi` |
| `serviceAccount.create` | Create service account | `true` |

## Examples

See the `examples` directory for sample values files.

## Troubleshooting

### Common Issues

1. **Pod not starting**: Check if the ServiceAccount exists and the PVC is properly bound.

   ```bash
   kubectl get serviceaccount -n <namespace>
   kubectl get pvc -n <namespace>
   ```

2. **Client can't connect to server**: Verify the server URL is correct and accessible from the client pod.

   ```bash
   kubectl exec -it <pod-name> -n <namespace> -- curl -v <server-url>
   ```

3. **Permission issues**: Check if the pod has the right permissions to access the mounted volumes.

   ```bash
   kubectl describe pod <pod-name> -n <namespace>
   ```

## License

This Helm chart is provided under the MIT License.