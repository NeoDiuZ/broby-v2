"""Serve both Railway's IPv4 health probes and IPv6 private-network requests."""
import os
import socket
import uvicorn

if __name__ == '__main__':
    with socket.create_server(('::', int(os.getenv('PORT', '8000'))),
                              family=socket.AF_INET6, dualstack_ipv6=True) as listener:
        server = uvicorn.Server(uvicorn.Config('main:app', timeout_graceful_shutdown=30))
        server.run(sockets=[listener])
