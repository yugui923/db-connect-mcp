FROM alpine:3.19

RUN apk add --no-cache openssh-server netcat-openbsd shadow

# Generate host keys
RUN ssh-keygen -A

# Create tunnel user
RUN adduser -D -s /bin/sh tunneluser

# Configure sshd
RUN sed -i \
        -e 's/#\?PasswordAuthentication.*/PasswordAuthentication yes/' \
        -e 's/#\?AllowTcpForwarding.*/AllowTcpForwarding yes/' \
        -e 's/#\?GatewayPorts.*/GatewayPorts no/' \
        -e 's/#\?PermitRootLogin.*/PermitRootLogin no/' \
        /etc/ssh/sshd_config

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
