"""Línea de órdenes del sistema multiagente. Se ejecuta desde la raíz del repositorio.

    python -m agentes doctor                     # qué hay disponible y qué no
    python -m agentes analizar [--json f.json]   # agente 1, solo
    python -m agentes prompt   --objetivo … --ficheros … [--prueba …]
    python -m agentes revisar  <ruta>            # agente 4, sobre código en disco
    python -m agentes pipeline --objetivo … --ficheros … --prueba … [--aplicar]
    python -m agentes happyrobot                 # sonda de la plataforma
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import proveedores
from .analizador import AnalizadorDeContexto
from .arquitecto import ArquitectoDePrompts
from .contratos import Accion, Encargo, Severidad, Veredicto
from .happyrobot import ClienteHappyRobot
from .orquestador import Orquestador
from .revisor import RevisorDeCodigo

MARCA = {
    Veredicto.ACEPTA: "ACEPTA",
    Veredicto.ACEPTA_CON_AVISOS: "ACEPTA CON AVISOS",
    Veredicto.PIDE_APROBACION: "ESPERA A UNA PERSONA",
    Veredicto.RECHAZA: "RECHAZA",
}


def _encargo_de(args: argparse.Namespace) -> Encargo:
    ficheros = [f.strip() for f in (args.ficheros or "").split(",") if f.strip()]
    return Encargo(
        objetivo=args.objetivo,
        ficheros_permitidos=ficheros,
        comando_prueba=args.prueba or "",
        accion=Accion(args.accion),
        contexto_extra=args.contexto or "",
        max_lineas=args.max_lineas,
    )


# ----------------------------------------------------------------------------------- subcomandos


def cmd_doctor(args: argparse.Namespace) -> int:
    print("PROVEEDORES DE MODELO")
    hay_uno = False
    for nombre, ok, detalle in proveedores.diagnostico():
        print(f"  {'✓' if ok else '✗'} {nombre:16} {detalle}")
        hay_uno = hay_uno or (ok and nombre != "seco")
    if not hay_uno:
        print("\n  No hay ningún modelo alcanzable. El sistema funciona igual en modo seco:")
        print("  los agentes 1, 2 y 4 son deterministas, y el 3 entrega el encargo para pegar a mano.")

    print("\nPLATAFORMA HAPPYROBOT")
    d = ClienteHappyRobot().diagnostico()
    print(f"  base {d['base']} · clúster {d['cluster']} · clave presente: {d['clave_presente']}")
    for p in d["pruebas"]:
        print(f"  {'✓' if p['ok'] else '✗'} {p['nombre']:16} HTTP {p['codigo']:<4} {p['detalle']}")
    print(f"  → {d['lectura']}")

    print("\nREPOSITORIO")
    ctx = AnalizadorDeContexto(args.raiz).analizar()
    print(f"  huella {ctx.generado_con} · {len(ctx.modulos)} módulos · {len(ctx.reglas)} reglas")
    for a in ctx.avisos:
        print(f"  ! {a}")
    return 0


def cmd_analizar(args: argparse.Namespace) -> int:
    ctx = AnalizadorDeContexto(args.raiz).analizar()
    if args.json:
        Path(args.json).write_text(
            json.dumps(ctx.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"escrito {args.json}")
        return 0

    print(f"HUELLA {ctx.generado_con}   ({ctx.raiz})\n")
    print(f"{'MÓDULO':22} {'DUEÑO':24} {'FICH':>5} {'LÍNEAS':>7} {'TESTS':>6}  DEPENDENCIAS")
    for m in ctx.modulos:
        deps = ", ".join(m.importa_externo) if m.importa_externo else "solo stdlib"
        print(f"{m.ruta:22} {m.dueno[:24]:24} {m.ficheros:5} {m.lineas:7} {len(m.tests):6}  {deps}")

    print(f"\nREGLAS DURAS ({sum(1 for r in ctx.reglas if r.severidad is Severidad.BLOQUEA)} bloquean):")
    for r in ctx.reglas:
        if r.severidad in (Severidad.BLOQUEA, Severidad.GRAVE):
            print(f"  {str(r.severidad).upper():8} {r.clave:32} {r.fuente}")

    if ctx.convenciones:
        print("\nCONVENCIONES:")
        for c in ctx.convenciones:
            print(f"  · {c}")
    if ctx.hitos:
        print("\nRELOJ:")
        for h in ctx.hitos[:6]:
            print(f"  · {h}")
    if ctx.avisos:
        print("\nLO QUE NO SE HA PODIDO LEER:")
        for a in ctx.avisos:
            print(f"  ! {a}")
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    ctx = AnalizadorDeContexto(args.raiz).analizar()
    encargo = _encargo_de(args)
    problemas = encargo.valido()
    spec = ArquitectoDePrompts(ctx).construir(encargo)

    if problemas:
        print("AVISO — el encargo llega incompleto:", file=sys.stderr)
        for p in problemas:
            print(f"  ! {p}", file=sys.stderr)
        print("", file=sys.stderr)

    if args.json:
        Path(args.json).write_text(
            json.dumps(spec.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"escrito {args.json}")
        return 0

    print("=" * 78)
    print("SISTEMA")
    print("=" * 78)
    print(spec.sistema)
    print()
    print("=" * 78)
    print("ENCARGO")
    print("=" * 78)
    print(spec.usuario)
    print()
    print(f"-- {spec.caracteres} caracteres · bloques: {', '.join(spec.piezas)}"
          + (f" · recortado: {', '.join(spec.recortado)}" if spec.recortado else ""))
    return 0


def cmd_revisar(args: argparse.Namespace) -> int:
    rev = RevisorDeCodigo().revisar_ruta(args.ruta)
    orden = [Severidad.BLOQUEA, Severidad.GRAVE, Severidad.AVISO, Severidad.NOTA]
    for s in orden:
        grupo = rev.por_severidad(s)
        if not grupo:
            continue
        if s is Severidad.NOTA and not args.todo:
            print(f"\nNOTA ({len(grupo)}) — se enseñan con `--todo`")
            continue
        print(f"\n{str(s).upper()} ({len(grupo)})")
        for a in grupo:
            donde = f"{a.fichero}:{a.linea}" if a.fichero else "-"
            print(f"  {donde}")
            print(f"    {a.regla}: {a.mensaje}")
            if a.fuente:
                print(f"    fuente: {a.fuente}")
    print(f"\nVEREDICTO: {MARCA[rev.veredicto]}   ({len(rev.avisos)} aviso(s))")
    print(f"comprobado: {', '.join(rev.comprobaciones)}")
    return 0 if rev.veredicto is not Veredicto.RECHAZA else 1


def cmd_pipeline(args: argparse.Namespace) -> int:
    prov = proveedores.construir(args.proveedor)
    if args.proveedor != "seco":
        ok, detalle = prov.disponible()
        if not ok:
            print(f"AVISO: «{args.proveedor}» no está disponible ({detalle}). Se sigue en modo seco.\n",
                  file=sys.stderr)
            prov = proveedores.construir("seco")

    orq = Orquestador(args.raiz, prov)
    res = orq.ejecutar(_encargo_de(args))

    print("TRAZA")
    for p in res.traza.pasos:
        print(f"  {p.agente:18} {p.ms:5} ms  {p.salida}")
        for n in p.notas[:6]:
            print(f"    · {n}")

    print(f"\nVEREDICTO: {MARCA[res.revision.veredicto]}")
    for a in res.revision.avisos:
        print(f"  {a}")

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    huella = res.traza.encargo.split(" ")[0]
    (salida / f"{huella}-traza.json").write_text(
        json.dumps(res.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if res.parche.encargo_para_humano:
        destino = salida / f"{huella}-encargo.md"
        destino.write_text(res.parche.encargo_para_humano, encoding="utf-8")
        print(f"\nEncargo listo para pegar: {destino}")
    print(f"Traza: {salida / (huella + '-traza.json')}")

    if args.aplicar:
        escritos = orq.aplicar(res)
        if escritos:
            print("\nEscritos: " + ", ".join(escritos))
        else:
            print("\nNo se ha escrito nada: el veredicto no lo permite o no había ficheros.")
    return 0 if res.revision.veredicto is not Veredicto.RECHAZA else 1


def cmd_happyrobot(args: argparse.Namespace) -> int:
    d = ClienteHappyRobot().diagnostico()
    print(json.dumps(d, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------------------------------ main


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m agentes", description="Sistema multiagente de FABAT")
    p.add_argument("--raiz", default=".", help="raíz del repositorio (por defecto, el directorio actual)")
    sub = p.add_subparsers(dest="orden", required=True)

    sub.add_parser("doctor", help="qué está disponible y qué no").set_defaults(func=cmd_doctor)

    a = sub.add_parser("analizar", help="agente 1: extrae el contexto del repositorio")
    a.add_argument("--json", help="escribir el ContextPack en este fichero")
    a.set_defaults(func=cmd_analizar)

    def comunes(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--objetivo", required=True, help="qué hay que hacer, en una frase")
        sp.add_argument("--ficheros", default="", help="ficheros que se pueden tocar, separados por comas")
        sp.add_argument("--prueba", default="", help="comando que demuestra que ha terminado")
        sp.add_argument("--accion", default="implementar", choices=[str(x) for x in Accion])
        sp.add_argument("--contexto", default="", help="contexto extra para el encargo")
        sp.add_argument("--max-lineas", type=int, default=400, dest="max_lineas")

    pr = sub.add_parser("prompt", help="agente 2: genera el prompt especializado")
    comunes(pr)
    pr.add_argument("--json", help="escribir el PromptSpec en este fichero")
    pr.set_defaults(func=cmd_prompt)

    rv = sub.add_parser("revisar", help="agente 4: revisa código que ya está en disco")
    rv.add_argument("ruta", help="fichero o carpeta")
    rv.add_argument("--todo", action="store_true", help="enseñar también las notas informativas")
    rv.set_defaults(func=cmd_revisar)

    pl = sub.add_parser("pipeline", help="los cuatro agentes, en orden, con traza")
    comunes(pl)
    pl.add_argument("--proveedor", default="seco", choices=list(proveedores.CATALOGO))
    pl.add_argument("--salida", default="agentes/salida", help="carpeta donde dejar traza y encargo")
    pl.add_argument("--aplicar", action="store_true", help="escribir los ficheros si el veredicto lo permite")
    pl.set_defaults(func=cmd_pipeline)

    hr = sub.add_parser("happyrobot", help="sonda de la plataforma (clúster EU)")
    hr.set_defaults(func=cmd_happyrobot)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
