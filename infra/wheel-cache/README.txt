Empty by default. The normal build downloads the frozen uv.lock dependencies.
For a slow or offline network, buildx can override this stage with
--build-context wheel-cache=/path/to/verified-platform-wheels
The context is mounted during installation only and is not copied into images.
