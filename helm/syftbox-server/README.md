# SyftBox Server Helm Chart

A Helm chart for deploying a SyftBox server on Kubernetes.

## Overview

This chart deploys a SyftBox server that can be used as a synchronization server for SyftBox clients. The server can be deployed using either a Deployment or StatefulSet based on your requirements, with StatefulSet recommended for production use.

## Prerequisites

- Kubernetes 1.16+
- Helm 3.0+
- Dynamic storage provisioner (or pre-created PersistentVolumes)

## Installation

```bash
# Create a namespace for SyftBox components
kubectl create namespace syftbox-system

# Install the chart with default values
helm install syftbox-server ./syftbox-server --namespace syftbox-system

# Install with custom values file
helm install syftbox-server ./syftbox-server -f values.yaml --namespace syftbox-system

# Install with specific overrides
helm install syftbox-server ./syftbox-server --set deploymentType=statefulset --set persistence.size=10Gi
```

## Deployment Types

You can choose between two deployment types:

1. **Deployment**:
   ```yaml
   deploymentType: "deployment"
   ```
   
   Simple deployment with a PVC.

2. **StatefulSet** (recommended for production):
   ```yaml
   deploymentType: "statefulset"
   ```
   
   Better for stable storage and network identity.

## Service Configuration

The server is exposed through a Kubernetes Service:

```yaml
service:
  type: ClusterIP  # Or LoadBalancer, NodePort
  port: 8000
  annotations:
    # Add custom annotations if needed
```

## Ingress Configuration

For external access, you can enable an Ingress:

```yaml
ingress:
  enabled: true
  className: "nginx"
  hosts:
    - host: syftbox-server.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: syftbox-server-tls
      hosts:
        - syftbox-server.example.com
```

## Persistence Configuration

Configure persistent storage:

```yaml
persistence:
  enabled: true
  storageClass: "standard"  # Use your preferred storage class
  size: 5Gi
```

## Resources

Set resource requests and limits:

```yaml
resources:
  limits:
    cpu: 2000m
    memory: 2Gi
  requests:
    cpu: 1000m
    memory: 1Gi
```

## Client Connection

After deploying the server, clients can connect to it using:
- Within the same cluster: `http://syftbox-server.syftbox-system.svc.cluster.local:8000`
- External access: Via the Ingress hostname or LoadBalancer IP

## Key Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `deploymentType` | Type of deployment (`deployment` or `statefulset`) | `statefulset` |
| `server.port` | Server port | `8000` |
| `server.configPath` | Configuration path inside container | `/config/syftbox/config.json` |
| `server.config` | Configuration file content | See values.yaml |
| `service.type` | Type of service | `ClusterIP` |
| `service.port` | Service port | `8000` |
| `ingress.enabled` | Enable ingress | `false` |
| `persistence.enabled` | Enable persistent storage | `true` |
| `persistence.size` | Size of persistent volume | `5Gi` |
| `serviceAccount.create` | Create service account | `true` |

## Troubleshooting

### Common Issues

1. **Pod not starting**: Check if the ServiceAccount exists and the PVC is properly bound.

   ```bash
   kubectl get serviceaccount -n <namespace>
   kubectl get pvc -n <namespace>
   ```

2. **Server not accessible**: Verify the service and endpoints are created correctly.

   ```bash
   kubectl get service -n <namespace>
   kubectl get endpoints -n <namespace>
   ```

3. **Permission issues**: Check if the pod has the right permissions to access the mounted volumes.

   ```bash
   kubectl describe pod <pod-name> -n <namespace>
   ```

## License

This Helm chart is provided under the MIT License.