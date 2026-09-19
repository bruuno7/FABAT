import { redirect } from "next/navigation";

/**
 * `/webcall` ya no es una pantalla: el puesto de llamada es el panel de chat de
 * la columna derecha de la pantalla única (`/`).
 *
 * Se mantiene la ruta como redirección permanente para no romper enlaces
 * existentes ni dejar una página muerta (COMPLIANCE: nada de enlaces rotos).
 */
export default function WebCallRedirect() {
  redirect("/");
}
