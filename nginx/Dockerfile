FROM nginx:alpine

COPY nginx.conf /etc/nginx/nginx.conf
COPY ssl/cert.pem /etc/nginx/ssl/cert.pem
COPY ssl/key.pem /etc/nginx/ssl/key.pem

RUN chown -R nginx:nginx /etc/nginx/ssl && \
    chmod 600 /etc/nginx/ssl/key.pem && \
    chmod 644 /etc/nginx/ssl/cert.pem

EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]