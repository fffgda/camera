FROM eclipse-mosquitto:2
USER root
RUN mkdir -p /mosquitto/data /mosquitto/log && \
    chown -R mosquitto:mosquitto /mosquitto/data /mosquitto/log
COPY mosquitto.conf /mosquitto/config/mosquitto.conf
USER mosquitto
EXPOSE 1883
CMD ["-c", "/mosquitto/config/mosquitto.conf"]
