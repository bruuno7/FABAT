import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /*
   * El repo tiene otro package-lock.json en la raiz (fuera de `web/`, para los
   * scripts de `motor/` y `puente/`). Sin esto, Turbopack duda entre los dos
   * lockfiles y adivina mal la raiz del workspace: eso rompe el cache de
   * `.next` con errores intermitentes de rename (visto en desarrollo al
   * levantar el servidor). Fijar la raiz aqui lo hace determinista.
   */
  turbopack: {
    root: path.join(__dirname),
  },
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
