# Docker Image Pieces

The Docker image is split into parts to stay under GitHub's file size limits.

## Reassemble

```bash
cat part_* > gps-sql-visualizer.tar.gz
```

## Verify integrity

```bash
md5sum -c checksums.md5
```

## Load into Docker

```bash
docker load < gps-sql-visualizer.tar.gz
```
