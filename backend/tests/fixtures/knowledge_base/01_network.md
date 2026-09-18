# Network architecture

## Production

The production network is `203.0.113.0/24`. The database host `EXAMPLE-DB01` uses
`203.0.113.10`. Access from the corporate network `10.0.0.0/16` should use
an approved bastion.

## Scanner exception

The authorized vulnerability scanner at `198.51.100.50` performs port scans.
