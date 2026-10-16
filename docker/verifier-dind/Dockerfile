FROM docker:29-dind
COPY entrypoint.sh /usr/local/bin/autocve-dind-entrypoint.sh
RUN chmod 0755 /usr/local/bin/autocve-dind-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/autocve-dind-entrypoint.sh"]
