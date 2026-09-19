import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";

/* Tipografía de la referencia de estilo del usuario.
   COMPLIANCE/nota técnica: no se usa `@import` ni CDN; `next/font/google`
   descarga y sirve la fuente localmente en build, sin peticiones en runtime. */
const jakarta = Plus_Jakarta_Sans({
  variable: "--font-jakarta",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "MANDO · Sala de control",
  description:
    "HappyRobot habla; MANDO decide. Plano del recinto, dotación de recursos y mesa de decisión para el Festival Abierto.",
};

/*
 * Shell mínimo: el layout aporta las restricciones de altura y el atajo de
 * teclado. La barra lateral y el reparto de regiones viven en `page.tsx` porque
 * hay UNA SOLA PANTALLA y el estado de sus filtros y paneles es estado de esa
 * pantalla (no hay chrome compartido entre rutas que justifique el layout).
 */
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="es-ES"
      className={`${jakarta.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col bg-bg text-ink xl:h-dvh xl:overflow-hidden">
        {/* COMPLIANCE (WCAG 2.4.1): atajo de teclado al contenido principal. */}
        <a href="#contenido" className="skip-link">
          Saltar al contenido principal
        </a>
        {children}
      </body>
    </html>
  );
}
