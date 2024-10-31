# Use the official Nginx image
FROM nginx:alpine

# Set up environment variables for SSL
ENV DOMAIN madhava.syftbox.madhavajay.com

# Copy the custom Nginx configuration file
COPY nginx.conf /etc/nginx/nginx.conf

# Copy the SSL certificates (fullchain and privkey)
COPY certs/fullchain.pem /etc/letsencrypt/live/$DOMAIN/fullchain.pem
COPY certs/privkey.pem /etc/letsencrypt/live/$DOMAIN/privkey.pem

# Expose port 443 for HTTPS
EXPOSE 443

# Expose port 80 for redirection to HTTPS
EXPOSE 80

# Start Nginx server
CMD ["nginx", "-g", "daemon off;"]
