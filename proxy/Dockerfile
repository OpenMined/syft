# docker build -f proxy/Dockerfile -t syftbox-proxy proxy
# docker run -d -p 80:80 -v $(pwd)/proxy/nginx.conf:/etc/nginx/nginx.conf syftbox-proxy


# Use an official Nginx base image
FROM nginx:alpine

# Install inotify-tools to monitor file changes
RUN apk update && apk add inotify-tools

# Copy your custom Nginx configuration (optional, if needed)
COPY ./nginx.conf /etc/nginx/nginx.conf

# Copy the hot-reload bash script to the container
COPY ./start.sh /usr/local/bin/nginx-reload.sh

# Make the bash script executable
RUN chmod +x /usr/local/bin/nginx-reload.sh

# Expose port 80 for HTTP traffic
EXPOSE 80

# Start the bash script in the background and Nginx in the foreground
CMD ["/bin/sh", "-c", "/usr/local/bin/nginx-reload.sh & nginx -g 'daemon off;'"]
