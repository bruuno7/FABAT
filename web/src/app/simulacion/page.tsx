import { redirect } from "next/navigation";

/**
 * `/simulacion` ya no es una pantalla: los controles de inyección viven en el
 * cajón "Preparación" de la pantalla única (`/`).
 *
 * Se mantiene la ruta como redirección permanente para no romper enlaces
 * existentes ni dejar una página muerta (COMPLIANCE: nada de enlaces rotos).
 */
export default function SimulacionRedirect() {
  redirect("/");
}
