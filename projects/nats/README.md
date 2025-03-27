###

Launching the container:

```
docker run -p 4222:4222 -v ./nats_data:/data nats -js -sd /data

# OR

docker compose up
```

### Subjects

```
1. Client requests to server
pub to requests.{requester}.{responder}.{app_name}

2. Server listens for requests
sub to requests.*.{responder}.{app_name}

3. Server responds to client
pub to responses.{requester}.{responder}.{app_name}.{request_id}

4. Client listens for responses
sub to responses.{requester}.{responder}.{app_name}.{request_id}
```
