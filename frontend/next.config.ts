import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async redirects() {
    return [
      {
        source: "/tenants",
        destination: "/dashboard/admin/tenants",
        permanent: false,
      },
      {
        source: "/tenants/new",
        destination: "/dashboard/admin/tenants",
        permanent: false,
      },
      {
        source: "/tenants/:tenantId",
        destination: "/dashboard/admin/tenants/:tenantId",
        permanent: false,
      },
      {
        source: "/tenants/:tenantId/playbooks",
        destination: "/dashboard/:tenantId/playbooks",
        permanent: false,
      },
      {
        source: "/tenants/:tenantId/playbooks/new",
        destination: "/dashboard/:tenantId/playbooks/new",
        permanent: false,
      },
      {
        source: "/tenants/:tenantId/playbooks/:playbookId",
        destination: "/dashboard/:tenantId/playbooks/:playbookId",
        permanent: false,
      },
      {
        source: "/tenants/:tenantId/schema-registry",
        destination: "/dashboard/:tenantId/schema-registry",
        permanent: false,
      },
      {
        source: "/tenants/:tenantId/schema-registry/new",
        destination: "/dashboard/:tenantId/schema-registry/new",
        permanent: false,
      },
    ];
  },
};

export default nextConfig;
