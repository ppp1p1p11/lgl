import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts", "lib/api/schema.d.ts"] },
  ...nextCoreWebVitals,
  ...nextTypescript,
];

export default config;
