import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /*
   * La interfaz de MANDO Ops se sirve como página estática desde
   * `public/interfaz.html` (Next publica el contenido de `public/` en la raíz).
   * Esta rewrite permite abrirla como `/interfaz`, sin el `.html`, sin crear una
   * ruta ni tocar ninguna pantalla existente.
   *
   * Es aditiva: si más adelante se quiere una ruta propia, basta con borrar esta
   * entrada y mover el fichero a `src/app/interfaz/`.
   */
  async rewrites() {
    return [{ source: "/interfaz", destination: "/interfaz.html" }];
  },
};

export default nextConfig;
