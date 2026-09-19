"use client";

import { useCallback, useEffect, useState } from "react";
import type { Board } from "@/lib/board-types";
import { fetchBoard } from "@/lib/client-api";

/**
 * Estado del tablero compartido por las tres pantallas.
 *
 * Se extrae a un hook por dos motivos concretos:
 *  1. el refresco cada 2,5 s debe comportarse IGUAL en todas las vistas;
 *  2. hay que garantizar que el refresco no rompe la interfaz. Aquí se hace así:
 *     - el estado se sustituye entero (`setBoard(data)`), sin tocar la selección,
 *       el foco ni el scroll, que viven en los componentes;
 *     - la primera carga se difiere a un temporizador, para no llamar a setState
 *       de forma síncrona dentro del efecto (evita renders en cascada);
 *     - el intervalo se limpia al pausar y al desmontar.
 */
export function useBoard(pollMs = 2500) {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(true);

  const reload = useCallback(async () => {
    try {
      setBoard(await fetchBoard());
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(() => void reload(), 0);
    return () => clearTimeout(first);
  }, [reload]);

  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => void reload(), pollMs);
    return () => clearInterval(timer);
  }, [live, reload, pollMs]);

  return { board, error, live, setLive, reload };
}

/**
 * Reloj de baja frecuencia (30 s). Alimenta las antigüedades del tipo "hace 3m"
 * sin repintar la consola cada segundo. Arranca en `null` a propósito: en el
 * primer render (servidor y cliente) no se pinta ninguna edad relativa, así no
 * hay desajuste de hidratación.
 */
export function useNow(intervalMs = 30000) {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    const tick = () => setNow(new Date());
    const first = setTimeout(tick, 0);
    const timer = setInterval(tick, intervalMs);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [intervalMs]);
  return now;
}
