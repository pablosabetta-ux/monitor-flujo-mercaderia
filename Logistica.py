import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
import requests
import numpy as np

# Configuración de la página de Streamlit
st.set_page_config(layout="wide", page_title="Análisis de Ineficiencias Logísticas")
st.title("📊 Monitor de Flujos, Ineficiencias y Cuellos de Botella")
st.write("Visualización dinámica del movimiento de kilos y detección de rulos logísticos.")

archivo_cargado = st.file_uploader("Subí tu archivo de movimientos (Excel)", type=["xls", "xlsx"])

if archivo_cargado is not None:
    try:
        @st.cache_data
        def cargar_y_procesar(file):
           # 1. Leer el Excel
            df = pd.read_excel(file, sheet_name=0)
            df.columns = df.columns.str.strip()
            
            # 2. Forzar Fecha
            df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
            # 3. Forzar Cantidad a Número Puro
            df['Cantidad'] = pd.to_numeric(df['Cantidad'], errors='coerce').fillna(0)
            # Normalizar columna de kilos: algunos archivos usan 'Kilos' en lugar de 'Cantidad'
            if 'Kilos' not in df.columns:
                df['Kilos'] = df['Cantidad']
            # 4. BLINDAJE CRÍTICO: Forzar Lote a Texto Puro (así evitamos el error de comparación)
            # Primero cambiamos los vacíos por la palabra "SIN_LOTE"
            df['NroLote'] = df['NroLote'].fillna("SIN_LOTE")
            # Convertimos todo a string y limpiamos espacios
            df['NroLote'] = df['NroLote'].astype(str).str.strip()
            # 5. Asegurar que DEPOSITO y TP sean texto y no tengan nulos
            df['DEPOSITO'] = df['DEPOSITO'].fillna("DESCONOCIDO").astype(str).str.strip()
            df['TP'] = df['TP'].fillna("SIN_TP").astype(str).str.strip()
            df['NomArticulo'] = df['NomArticulo'].fillna("DESCONOCIDO").astype(str).str.strip()
            df['NOMBRE'] = df['NOMBRE'].fillna("DESCONOCIDO").astype(str).str.strip()

            # --- LEER HOJA "CLIENTES" ---
            clientes_dict = {}
            try:
                df_clientes = pd.read_excel(file, sheet_name="CLIENTES")
                df_clientes.columns = df_clientes.columns.str.strip().str.upper()
                
                for _, row in df_clientes.iterrows():
                    id_cliente = str(row['NOMBRE']).strip().upper()
                    lat_c = pd.to_numeric(row['LAT'], errors='coerce')
                    lon_c = pd.to_numeric(row['LONG'], errors='coerce')
                    loc_name = str(row['LOCALIDAD']).split(',')[0] if 'LOCALIDAD' in df_clientes.columns else "Cliente"
                    
                    if not pd.isna(lat_c) and not pd.isna(lon_c):
                        clientes_dict[id_cliente] = {
                            "localidad": loc_name,
                            "lat": float(lat_c),
                            "lon": float(lon_c)
                        }
            except Exception as e:
                st.sidebar.warning(f"Aviso en pestaña 'CLIENTES': {e}")

            # --- LEER HOJA DE DEPOSITOS DINÁMICA ---
            coordenadas_dict = {}
            try:
                df_depos = pd.read_excel(file, sheet_name="DEPOS")
                df_depos.columns = df_depos.columns.str.strip().str.upper() # Pasamos a mayúsculas para evitar fallos de tipeo
                
                # Mapeo de columnas requeridas según tu estructura del Excel
                col_dep = 'DEPOSITO'
                col_lat = 'LAT'
                # Toleramos si escribiste LONG o LONGITUD en el Excel
                col_lon = 'LONG' if 'LONG' in df_depos.columns else ('LONGITUD' if 'LONGITUD' in df_depos.columns else None)
                
                if col_lon and col_lat in df_depos.columns and col_dep in df_depos.columns:
                    for _, row in df_depos.iterrows():
                        # Guardamos la clave en MAYÚSCULAS para evitar discrepancias de tipeo (ej. "Pergamino" vs "PERGAMINO")
                        dep_name = str(row[col_dep]).strip().upper()
                        coordenadas_dict[dep_name] = {
                            "lat": float(row[col_lat]),
                            "lon": float(row[col_lon])
                        }
                else:
                    st.sidebar.error("⚠️ La hoja 'DEPOS' debe tener las columnas: DEPOSITO, LAT, LONG")
            except Exception as e:
                st.sidebar.error(f"No se pudo procesar la hoja 'DEPOS'. Detalle: {e}")

            # Agregar/Asegurar los nodos virtuales que maneja la lógica de derivación
            nodos_virtuales = {
                "PROVEEDOR EXT.":        {"lat": -34.5936, "lon": -58.3715}, 
                "PROVEEDOR LOCALES":     {"lat": -34.5936, "lon": -58.3715}, 
                "CLIENTE (VENTA)":       {"lat": -32.9468, "lon": -60.6393}, 
                "MERCADERÍA EN TRÁNSITO": {"lat": -34.3000, "lon": -59.5000}, 
                "AJUSTES DE INVENTARIO":  {"lat": -33.8923, "lon": -60.5735}, 
                "LINEA PROCESO (VIRT.)":  {"lat": -33.8923, "lon": -60.5735},
                "DESCONOCIDO":            {"lat": -34.6037, "lon": -58.3816},
                "DESPACHO DIRECTO":       {"lat": -33.8923, "lon": -60.5735},
                "0":              {"lat": -33.8923, "lon": -60.5735}
            }

            # Combinamos lo del Excel con los virtuales (el Excel tiene prioridad si se repite nombre)
            COORDENADAS_FINAL = {**nodos_virtuales, **coordenadas_dict}

            return df, COORDENADAS_FINAL, clientes_dict

        df_base, COORDENADAS, clientes_dict = cargar_y_procesar(archivo_cargado)

        # ----  Función auxiliar cacheada para obtener el GeoJSON de las provincias argentinas sin saturar la red
        @st.cache_data
        def obtener_geojson_provincias():
            url = "https://raw.githubusercontent.com/mgaitan/un-mapa-de-argentina-en-r/master/argentina.json"
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    return response.json()
            except Exception:
                pass
            return None
        df_base, COORDENADAS, clientes_dict = cargar_y_procesar(archivo_cargado)
        geojson_provincias = obtener_geojson_provincias()


        # ==================================================================
        # 2. MENÚ PRINCIPAL Y BARRA LATERAL (CONTROL DE PANTALLAS)
        # ==================================================================
        
        # El selector principal que determina qué pantalla se dibuja a la derecha
        pantalla_activa = st.sidebar.radio(
            "Seleccioná la herramienta:",
            ["📊 Monitoreo de Stock y Flujos", "📦 Consolidación de Viajes (Eficiencia)", "🏭 Análisis de Hubs (Nuevos Depósitos)"]
        )
        
        st.sidebar.markdown("---")

        # ------------------------------------------------------------------
        # CONDICIÓN A: FILTROS EXCLUSIVOS PARA EL MONITOREO DE STOCK
        # ------------------------------------------------------------------
        if pantalla_activa == "📊 Monitoreo de Stock y Flujos":
            st.sidebar.header("Filtros Operativos")
            
            # Filtro por Familia primero, para acotar
            familias = sorted(df_base['FAMILIA'].dropna().astype(str).unique())
            #familia_sel = st.sidebar.selectbox("1. Filtrar por Familia:", ["TODAS"] + familias)
            familia_sel = st.sidebar.selectbox("1. Filtrar por Familia:", familias)
            
            if familia_sel != "TODAS":
                    df_especies_filtradas = df_base[df_base['FAMILIA'] == familia_sel]
            else:
                    df_especies_filtradas = df_base
            
            especies_disponibles = sorted(df_especies_filtradas['Species'].dropna().unique())
            #opciones_especie = ["TODAS"] + especies_disponibles
            opciones_especie = especies_disponibles

            especie_seleccionada = st.sidebar.selectbox("🌱 Filtrar por Especie:", opciones_especie)
        
            # Nivel 3: Selección de Artículo / Producto (Filtrado en cascada por los anteriores)
            df_articulos_filtrados = df_especies_filtradas.copy()
            if especie_seleccionada != "TODAS":
                df_articulos_filtrados = df_articulos_filtrados[df_articulos_filtrados['Species'] == especie_seleccionada]
                
            df_articulo = sorted(df_articulos_filtrados['NomArticulo'].dropna().unique())
            articulo_sel = st.sidebar.selectbox("📦 Seleccionar Artículo:", ["TODOS"] + df_articulo)        

            # --- FILTRADO DINÁMICO BASE DE DATOS ---
            df_filtrado = df_base[df_base['NomArticulo'] == articulo_sel].copy()
            if familia_sel != "TODAS":
                df_filtrado = df_filtrado[df_filtrado['FAMILIA'] == familia_sel]
            if especie_seleccionada != "TODAS":
                df_filtrado = df_filtrado[df_filtrado['Species'] == especie_seleccionada]

            # --- FILTROS DE TIEMPO UNIFICADOS ---
            st.sidebar.markdown("---")
            st.sidebar.header("⏱️ Rango de tiempo y mes")

            # Selector de Rango de Fechas basado en lo filtrado
            fecha_min = df_filtrado['Fecha'].min().date()
            fecha_max = df_filtrado['Fecha'].max().date()

            fechas = st.sidebar.date_input(
                "Rango de fechas:",
                value=[fecha_min, fecha_max],
                min_value=fecha_min,
                max_value=fecha_max
            )

            if len(fechas) == 2:
                df_filtrado = df_filtrado[
                    (df_filtrado['Fecha'].dt.date >= fechas[0]) & 
                    (df_filtrado['Fecha'].dt.date <= fechas[1])
                ]

            # Control de tiempo adicional por MES para acumulados hasta el mes seleccionado
            if 'MES' in df_filtrado.columns:
                meses_disponibles = sorted(df_filtrado['MES'].dropna().unique())
            else:
                meses_disponibles = []

            if len(meses_disponibles) > 0:
                ultimo_indice = len(meses_disponibles) - 1

                if "mes_index" not in st.session_state:
                    st.session_state.mes_index = ultimo_indice

                if st.session_state.mes_index >= len(meses_disponibles) or st.session_state.get('ultimo_articulo_visto') != articulo_sel:
                    st.session_state.mes_index = ultimo_indice
                    st.session_state.ultimo_articulo_visto = articulo_sel

                boton_play = st.sidebar.button("▶️ Reproducir Evolución")
                if boton_play:
                    for i in range(len(meses_disponibles)):
                        st.session_state.mes_index = i
                        time.sleep(0.8)
                        if i < ultimo_indice:
                            st.rerun()

                mes_seleccionado = st.sidebar.select_slider(
                    "Hasta el mes:", 
                    options=meses_disponibles,
                    value=meses_disponibles[st.session_state.mes_index],
                    key="slider_tiempo"
                )

                st.session_state.mes_index = meses_disponibles.index(mes_seleccionado)
                df_filtrado = df_filtrado[df_filtrado['MES'] <= mes_seleccionado].copy()
            else:
                st.sidebar.info("El filtro por mes no está disponible porque no existe la columna MES en los datos seleccionados.")

            # COMANDO: Control de apertura geográfica solicitado
            st.sidebar.markdown("---")
            st.sidebar.header("⚙️ Configuración del Mapa")
            apertura_cliente_sel = st.sidebar.radio("Apertura Cliente:", ["NO", "SI"], index=0, help="Determina si el mapa proyecta los clientes individualmente o consolidados.")
            apertura_cliente = (apertura_cliente_sel == "SI")


        # ==================================================================
        # PANTALLA 1: PREPARACIÓN EXCLUSIVA PARA EL SANKEY Y EL MAPA DE FLUJO
        # ==================================================================
        if pantalla_activa == "📊 Monitoreo de Stock y Flujos":
        
            # Filtramos los ingresos de tránsito (valores positivos) y limpiamos lotes
            ingresos_t = df_filtrado[(df_filtrado['TP'] == 'TRANSITO') & (df_filtrado['Kilos'] > 0)].copy()
            ingresos_t['Lote_Clean'] = ingresos_t['NroLote'].astype(str).str.strip().str.upper()
            
            # Diccionario para saber a qué depósito fue cada lote
            transito_por_lote = dict(zip(ingresos_t['Lote_Clean'], ingresos_t['DEPOSITO']))

            orig_dest_sankey = []
                
            for idx, row in df_filtrado.iterrows():
                            
                tp = str(row['TP']).strip()
                dep = str(row['DEPOSITO']).strip()

                # MODIFICACIÓN: Agregamos 'INI' a la lista de exclusión. Ya NO genera flechas de flujo.
                #if tp in ["SIN_TP", "FIN", "INI"] or dep == "DESCONOCIDO":
                #if tp in ["SIN_TP", "TRANSITO"] or dep == "DESCONOCIDO":
                if tp in ["SIN_TP"] or dep == "DESCONOCIDO":
                    continue                
            
                kg = float(row['Cantidad'])
                lote = row['NroLote']
                
                # Evitamos procesar lotes que no tengan tracking real si así lo deseamos
                if lote == "SIN_LOTE" or lote == "nan":
                    continue

                orig, dest = None, None
                
                if tp == 'FOB':
                    orig, dest = "Proveedor Ext.", dep
                elif tp == 'CPRA':
                    orig, dest = "Proveedor Local", dep
                elif tp == 'INI':
                    orig, dest = "Stock Inicial (Virt.)", dep
                elif tp == 'CMV':
                    orig, dest = dep, "Cliente (Venta)"
                elif tp == 'Baja_PRODUCC':
                    # La materia prima sale del depósito y se introduce en la línea de proceso
                    orig, dest = dep, "Linea Proceso (Virt.)"
                elif tp == 'PRODUCC':
                    # Lo que sale de la industria y vuelve limpio al stock del depósito
                    if kg > 0:
                        orig, dest = "Linea Proceso (Virt.)", dep
                    else:
                        # Rueda de auxilio por si hay algún contra-asiento negativo de producción
                        orig, dest = dep, "Linea Proceso (Virt.)"
                
                elif tp == 'TRANSITO':
                    if kg < 0:  # Evaluamos solo la salida física del camión
                        orig = dep
                        # Buscamos la contraparte exacta utilizando el lote limpio
                        if lote in transito_por_lote:
                            dest = transito_por_lote[lote]
                        else:
                            # Si el camión sigue viajando a fin de mes, cae en el nodo flotante
                            dest = "Mercadería en Tránsito"
                    else:
                        # El ingreso positivo (> 0) se saltea por completo.
                        # De esta forma evitamos duplicar la flecha y engordar el Sankey artificialmente.
                        continue
                
                elif tp in ['Ajuste', 'Ajuste_Evol']:
                    if kg > 0:
                        orig, dest = "Ajustes de Inventario", dep
                    else:
                        orig, dest = dep, "Ajustes de Inventario"
                
                # Si es FIN o no aplica, lo salteamos del flujo direccional
                if orig and dest:

                    orig_dest_sankey.append({
                        'Fecha': row['Fecha'],
                        'Lote': row['NroLote'],
                        'Origen': orig,
                        'Destino': dest,
                        'Kilos': abs(kg),
                        'Tipo_Movimiento': tp
                    })
                    
            df_flujo_sankey = pd.DataFrame(orig_dest_sankey)

            # =========================================================
            # LÓGICA 2: PREPARACIÓN EXCLUSIVA PARA EL MAPA GEOGRÁFICO
            # =========================================================

            orig_dest_mapa = []
            volumen_por_localidad = {}

            # ==================================================================
            # 1. PREPARACIÓN ULTRA-ESTRICTA DE TRÁNSITOS (LOTE COMPLETO)
            # ==================================================================
            # # Filtramos los ingresos de tránsito y limpiamos los textos de los lotes
            ingresos_t = df_filtrado[(df_filtrado['TP'] == 'TRANSITO') & (df_filtrado['Kilos'] > 0)].copy()
            
            # Pasamos a mayúsculas y quitamos espacios fantasmas para asegurar el cruce
            ingresos_t['Lote_Clean'] = ingresos_t['NroLote'].astype(str).str.strip().str.upper()
            
            # Creamos el diccionario de parejas: Clave = Lote Limpio -> Valor = Depósito Destino
            transito_por_lote = dict(zip(ingresos_t['Lote_Clean'], ingresos_t['DEPOSITO']))

            for idx, row in df_filtrado.iterrows():
                tp = row['TP']
                dep = row['DEPOSITO'].upper()
                # Limpiamos el lote actual de la fila de la misma manera exacta
                lote_actual = row['NroLote'].upper()

                if tp in ["SIN_TP", "FIN", "INI"] or dep in ["#N/A", "N/A", "NAN"]:
                #if tp in ["SIN_TP", "FIN"] or dep in ["#N/A", "N/A", "NAN"]:
                    continue            
            
                kg = float(row['Cantidad'])
                orig, dest = None, None
                
                if tp in ['FOB']:
                    orig, dest = "Proveedor Ext.", dep
                elif tp == 'CPRA':
                    orig, dest = "Proveedor Local", dep
                elif tp == 'INI':
                    orig, dest = "Stock Inicial (Virt.)", dep
                elif tp == 'CMV':
                    # Si el usuario seleccionó "NO" mostrar ventas en el mapa, salteamos la fila por completo
                    # NOTA: Cambiá 'mostrar_ventas' por el nombre de tu variable del botón/checkbox si es diferente
                    if apertura_cliente_sel=="SI":
                        id_cliente = row['NOMBRE']
                        #id_cliente = str(row['NOMBRE']).strip().upper()
                        
                        # Evaluación del botón de comando de apertura
                        if apertura_cliente and (id_cliente in clientes_dict):
                            orig = dep
                            dest = f"CLI_{id_cliente}_{idx}" # Token único por fila para mapa detallado
                            COORDENADAS[dest] = {
                                "lat": clientes_dict[id_cliente]['lat'],
                                "lon": clientes_dict[id_cliente]['lon'],
                                "display_name": f"Cliente: {id_cliente} ({clientes_dict[id_cliente]['localidad']})"
                            }
                        else:
                            orig, dest = dep, "CLIENTE (VENTA)"
                    
                elif tp == 'PRODUCC': 
                    orig, dest = ("LINEA PROCESO (VIRT.)", dep) if kg > 0 else (dep, "LINEA PROCESO (VIRT.)")
                
                elif tp == 'TRANSITO':
                    if kg < 0:  # Evaluamos solo el camión que sale cargado del depósito
                        orig = dep
                        # Buscamos su contraparte exacta en base al lote limpio
                        if lote_actual in transito_por_lote:
                            dest = transito_por_lote[lote_actual]
                        else:
                            # Rueda de auxilio si el camión sigue en viaje y no se recibió en el destino
                            dest = "Mercadería en Tránsito"
                    else:
                        continue  # El ingreso positivo se ignora para evitar duplicar el trazo en el mapa            
                
                elif tp in ['Ajuste', 'Ajuste_Evol']: 
                    orig, dest = ("AJUSTES DE INVENTARIO", dep) if kg > 0 else (dep, "AJUSTES DE INVENTARIO")

                if orig and dest:
                    orig_u = orig.upper()
                    dest_u = dest.upper()
                    kg_abs = abs(kg)
                    orig_dest_mapa.append({'Origen': orig_u, 'Destino': dest_u, 'Kilos': kg_abs, 'TP': tp})
                    volumen_por_localidad[orig_u] = volumen_por_localidad.get(orig_u, 0) + kg_abs
                    volumen_por_localidad[dest_u] = volumen_por_localidad.get(dest_u, 0) + kg_abs

            df_flujo_mapa = pd.DataFrame(orig_dest_mapa)

            # --- DISPARO DE COMPONENTES EN PANTALLA ---

            # --- DETECCIÓN DE INEFICIENCIAS (RULOS POR LOTE) ---
            st.subheader("⚠️ Alertas de Ineficiencias y Rulos Logísticos")
                
            df_internos = df_flujo_sankey[
                ~df_flujo_sankey['Origen'].str.contains("Proveedor|Inicial|Ajustes|Linea") & 
                ~df_flujo_sankey['Destino'].str.contains("Cliente|Baja|Ajustes|Linea")
            ]
            
            if not df_internos.empty:
                movimientos_por_lote = df_internos.groupby('Lote').size()
                lotes_con_rulos = movimientos_por_lote[movimientos_por_lote > 1]
                
                if not lotes_con_rulos.empty:
                    st.error(f"Se detectaron {len(lotes_con_rulos)} Lotes con re-despacho interno en este mes.")
                    df_alertas_lote = df_flujo_sankey[df_flujo_sankey['Lote'].isin(lotes_con_rulos.index)].copy()
                    df_alertas_lote['Fecha'] = df_alertas_lote['Fecha'].dt.strftime('%Y-%m-%d')
                    st.dataframe(df_alertas_lote[['Lote', 'Fecha', 'Origen', 'Destino', 'Kilos']].sort_values(by=['Lote', 'Fecha']), hide_index=True, use_container_width=True)
                else:
                    st.success("✅ ¡Logística Interna Eficiente! Sin rulos detectados en este período.")
            else:
                st.info("No se registran movimientos inter-depósitos en este mes.")
            st.markdown("---")

            # --- DIBUJO DEL MAPA DE FLUJO (SANKEY) ---
            st.subheader("Mapa de Flujo (Sankey)")
            if df_flujo_sankey.empty:
                    st.info("Sin datos para consolidar gráfico de Sankey.")
            else:
                nodos_sankey = list(pd.concat([df_flujo_sankey['Origen'], df_flujo_sankey['Destino']]).unique())
                nodo_a_id = {nodo: i for i, nodo in enumerate(nodos_sankey)}
                df_agrupado_sankey = df_flujo_sankey.groupby(['Origen', 'Destino', 'Tipo_Movimiento'], as_index=False)['Kilos'].sum()

                fuente = df_agrupado_sankey['Origen'].map(nodo_a_id).tolist()
                destino = df_agrupado_sankey['Destino'].map(nodo_a_id).tolist()
                valores = df_agrupado_sankey['Kilos'].tolist()
                etiquetas_flujo = df_agrupado_sankey['Tipo_Movimiento'].tolist()

                fig_sankey = go.Figure(data=[go.Sankey(
                    node=dict(pad=18, thickness=25, line=dict(color="black", width=0.5), label=nodos_sankey, color="teal"),
                    link=dict(source=fuente, target=destino, value=valores, label=etiquetas_flujo, color="rgba(102, 187, 106, 0.4)")
                )])
                
                fig_sankey.update_layout(title_text=f"Mapa de Distribución de Kilos: {articulo_sel}", height=550)
                st.plotly_chart(fig_sankey, use_container_width=True)
            
                # ------- CUADRO DE EVOLUCION 
                st.subheader("Detalle de Movimientos")
            
                # 1. Agrupamos los datos por Depósito y Tipo de Movimiento (TP)
                df_balance_dep = df_filtrado.groupby(['DEPOSITO', 'TP'], as_index=False)['Cantidad'].sum()

                # 2. Pivotamos la tabla para tener los TP como columnas individuales
                df_pivot = df_balance_dep.pivot(index='DEPOSITO', columns='TP', values='Cantidad').fillna(0)

                # 3. Aseguramos que todas las columnas de la ecuación existan (si no hay movimientos, que sea 0)
                columnas_tp = ['INI', 'CPRA', 'FOB', 'CMV', 'Baja_PRODUCC','PRODUCC', 'TRANSITO', 'AJUSTE', 'AJUSTE_EVOL', 'FIN']
                for col in columnas_tp:
                    if col not in df_pivot.columns:
                        df_pivot[col] = 0.0

                # 4. Construimos las columnas de tu ecuación exacta
                df_conciliacion = pd.DataFrame(index=df_pivot.index)
                
                # INICIO
                df_conciliacion['Inicio'] = df_pivot['INI']
                
                # COMPRAS (Sumamos CPRA y FOB si las manejás juntas)
                df_conciliacion['Compras'] = df_pivot['CPRA'] + df_pivot['FOB']
                
                # VENTAS (CMV entra restando, así que invertimos el signo para mostrar el flujo lógico salido)
                df_conciliacion['Ventas'] = df_pivot['CMV']
                
                # PROCESOS (Separamos según el signo de PRODUCC: negativo es salida a proceso, positivo es ingreso)
                # Nota: Si PRODUCC ya viene con signo en tu Excel, lo leemos directo:
                df_conciliacion['Salidas Proceso'] = -df_pivot['Baja_PRODUCC'].apply(lambda x: abs(x) if x < 0 else 0.0)
                df_conciliacion['Ingresos Proceso'] = df_pivot['PRODUCC'].apply(lambda x: x if x > 0 else 0.0)
                
                # TRANSITO (+- Tránsito)
                df_conciliacion['Tránsito'] = df_pivot['TRANSITO']
                
                # AJUSTES (Sumamos los tipos de ajuste)
                df_conciliacion['Ajustes'] = df_pivot['AJUSTE'] + df_pivot['AJUSTE_EVOL']
                
                # FIN (Stock Final Teórico o Real de la pestaña)
                df_conciliacion['Fin'] = df_pivot['FIN']

                # 5. AGREGAMOS LA FILA DE TOTALES GENERALES (Abajo del todo)
                # Calculamos la suma de cada columna numérica antes de meter la de control
                totales = df_conciliacion.sum(numeric_only=True)
                df_conciliacion.loc['TOTAL GENERAL'] = totales

                # 6. AGREGAMOS LA COLUMNA DE CONTROL (Al final de la fila)
                # Ecuación: Inicio + Compras - Ventas - Salidas Proceso + Ingresos Proceso + Tránsito + Ajustes - Fin
                # Nota: Si en tu Excel las Ventas (CMV) ya vienen con signo negativo, acá las sumamos en lugar de restar.
                # Evaluamos la ecuación estándar:
                df_conciliacion['Control (=0)'] = (
                    df_conciliacion['Inicio'] + 
                    df_conciliacion['Compras'] + 
                    df_conciliacion['Ventas'] + 
                    df_conciliacion['Salidas Proceso'] + 
                    df_conciliacion['Ingresos Proceso'] + 
                    df_conciliacion['Tránsito'] + 
                    df_conciliacion['Ajustes'] + 
                    df_conciliacion['Fin']
                )

                # 6. Ordenamos por stock Final de mayor a menor y reseteamos el índice para que el depósito sea columna
                df_conciliacion = df_conciliacion.sort_values(by='Fin', ascending=False).reset_index()
                df_conciliacion = df_conciliacion.rename(columns={'DEPOSITO': 'Depósito'})

                # 7. Configuración de formato numérico de Streamlit para conservar el orden correcto
                config_columnas = {
                    "Depósito": st.column_config.TextColumn("Depósito"),
                    "Inicio": st.column_config.NumberColumn("Inicio", format="%d"),
                    "Compras": st.column_config.NumberColumn("Compras (+)", format="%d"),
                    "Ventas": st.column_config.NumberColumn("Ventas (-)", format="%d"),
                    "Salidas Proceso": st.column_config.NumberColumn("Proc Out (-)", format="%d"),
                    "Ingresos Proceso": st.column_config.NumberColumn("Proc In (+)", format="%d"),
                    "Tránsito": st.column_config.NumberColumn("Tránsito (+/-)", format="%d"),
                    "Ajustes": st.column_config.NumberColumn("Ajustes (+/-)", format="%d"),
                    "Fin": st.column_config.NumberColumn("Fin (=)", format="%d")
                }

                # 8. Renderizamos la tabla en la interfaz
                st.dataframe(
                    df_conciliacion,
                    hide_index=True,
                    use_container_width=True,
                    height=520,
                    column_config=config_columnas
                )
            
            
                # --- SECCIÓN ENMARCADA INFERIOR: MAPA GEOGRÁFICO ---
                st.markdown("---")
            
                st.subheader("Análisis de Concentración")
                st.write("Volumen total manejado por tramo:")
                df_tabla_ver = df_agrupado_sankey.copy()
                
                st.dataframe(
                    df_tabla_ver.sort_values(by='Kilos', ascending=False),
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Kilos": st.column_config.NumberColumn(
                            "Kilos",
                            format="%d"  # Muestra los separadores de miles estándar del navegador
                        )
                    }
            )

                st.markdown("---")

                # ----- MAPA GEOGRÁFICO DE DEPÓSITOS (OPCIONAL) -----
                st.subheader("🗺️ Representación Geográfica de Entregas")
                
                # 🎛️ El interruptor para cambiar de dimensión en tiempo real
                modo_mapa = st.radio("Seleccioná la perspectiva del mapa:", ["Planos (2D)", "Volúmenes en Torres (3D)"], horizontal=True)

                if modo_mapa == "Planos (2D)":
                    if df_flujo_mapa.empty:
                        st.info("No hay coordenadas o tramos activos para proyectar geográficamente.")
                    else:
                        df_mapa_consolidado = df_flujo_mapa.groupby(['Origen', 'Destino', 'TP'], as_index=False)['Kilos'].sum()
                        fig_mapa = go.Figure()

                        # A. DIBUJAR CONTORNOS PROVINCIALES CON GEOJSON (SI ESTÁ DISPONIBLE)
                        if geojson_provincias:
                            for feature in geojson_provincias['features']:
                                prov_name = feature['properties'].get('name', 'Provincia')
                                geometry = feature['geometry']
                                coords_list = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
                                
                                for polygon in coords_list:
                                    # En GeoJSON el formato de cada anillo es [[lon, lat], [lon, lat], ...]
                                    # Si está anidado (MultiPolygon), extraemos el anillo principal
                                    ring = polygon[0] if isinstance(polygon[0][0], list) else polygon
                                    lons = [pt[0] for pt in ring]
                                    lats = [pt[1] for pt in ring]
                                    
                                    fig_mapa.add_trace(go.Scattergeo(
                                        lon = lons,
                                        lat = lats,
                                        mode = 'lines',
                                        line = dict(width = 1.2, color = '#28a745'), # Línea verde constante y definida
                                        hoverinfo = 'text',
                                        text = prov_name,
                                        showlegend = False
                                    ))

                    # 1. Dibujar las líneas de flujo (Vínculos geográficos)
                    max_kilos = df_mapa_consolidado['Kilos'].max() if not df_mapa_consolidado.empty else 1
                    
                    # B. Líneas Logísticas Dinámicas
                    max_kilos = df_mapa_consolidado['Kilos'].max() if not df_mapa_consolidado.empty else 1

                    # Listas para recolectar latitudes y longitudes de los tramos activos
                    lats_activas = []
                    lons_activas = []

                    for index, row in df_mapa_consolidado.iterrows():
                        o_name = str(row['Origen']).upper().strip()
                        d_name = str(row['Destino']).upper().strip()
                        tipo_p = row['TP']

                    # Si el origen es un campo roto o no está en la base de datos de depósitos, usamos el genérico
                        if o_name not in COORDENADAS:
                            o_name = "DESCONOCIDO"

                        # Si la apertura por cliente está activa y el destino es un cliente individual
                        if d_name.startswith("CLI_"):
                            # Extraemos el código limpio del cliente (ej: de 'CLI_2200007945_10' extrae '2200007945')
                            partes = d_name.split('_')
                            if len(partes) >= 2:
                                id_cliente_limpio = partes[1]
                                # Si el cliente existe en el diccionario importado de la pestaña CLIENTES
                                if id_cliente_limpio in clientes_dict:
                                    # Le inyectamos dinámicamente las coordenadas a la clave con ID único para que Plotly la encuentre
                                    COORDENADAS[d_name] = {
                                        "lat": clientes_dict[id_cliente_limpio]['lat'],
                                        "lon": clientes_dict[id_cliente_limpio]['lon'],
                                        "display_name": f"Cliente: {id_cliente_limpio} ({clientes_dict[id_cliente_limpio]['localidad']})"
                                    }

                        # Buscamos coordenadas en la matriz, si no existen salta
                        if o_name in COORDENADAS and d_name in COORDENADAS:
                            coord_orig = COORDENADAS[o_name]
                            coord_dest = COORDENADAS[d_name]
                            
                            # Guardamos los puntos para calcular el encuadre del zoom posterior
                            lats_activas.extend([coord_orig['lat'], coord_dest['lat']])
                            lons_activas.extend([coord_orig['lon'], coord_dest['lon']])

                            # El grosor de la línea depende del volumen de kilos trasladados
                            grosor = max(1.5, (row['Kilos'] / max_kilos) * 8)
                            color_linea = '#FFCC00' if tipo_p == 'CMV' else 'cyan'
                            
                            # Línea vectorizada entre Origen y Destino
                            fig_mapa.add_trace(go.Scattergeo(
                                    lon = [coord_orig['lon'], coord_dest['lon']],
                                    lat = [coord_orig['lat'], coord_dest['lat']],
                                    mode = 'lines', #'lines+markers',
                                    line = dict(width = grosor, color = color_linea),
                                    #marker = dict(size = 4, color = 'orange'),
                                    hoverinfo = 'text',
                                    text = f"Tramo: {o_name} ➡️ {d_name}<br>Volumen: {row['Kilos']:,.0f} Kg ({tipo_p})",
                                    showlegend = False
                                ))
                            
                        # C. Nodos, Pins de Clientes y Brillo por Volumen
                        for local_name, total_kg in volumen_por_localidad.items():
                            if local_name in COORDENADAS:
                                c = COORDENADAS[local_name]
                                is_cliente = local_name.startswith("CLI_")
                                label_mapa = c.get("display_name", local_name)
                                
                                if total_kg >= 100000 and not is_cliente:
                                    fig_mapa.add_trace(go.Scattergeo(
                                        lon = [c['lon']], lat = [c['lat']], mode = 'markers',
                                        marker = dict(size = 22, color = 'rgba(0, 255, 102, 0.35)', line = dict(width = 1.5, color = '#00FF66')),
                                        hoverinfo = 'skip', showlegend = False
                                    ))
                                
                                if is_cliente:
                                    color_nodo, tamaño_nodo = '#EFF542', 7
                                else:
                                    color_nodo = '#00FF66' if total_kg >= 100000 else 'orange'
                                    tamaño_nodo = 10 if total_kg >= 100000 else 6
                                
                                fig_mapa.add_trace(go.Scattergeo(
                                    lon = [c['lon']], lat = [c['lat']], mode = 'markers',
                                    marker = dict(size = tamaño_nodo, color = color_nodo), hoverinfo = 'text',
                                    hovertext = f"{label_mapa}<br>Volumen Acumulado: {total_kg:,.0f} Kg", showlegend = False
                                ))

                    # 2. Configurar la estética del Layout (Límites de provincias en VERDE, Fondo NEGRO)
                    if lats_activas and lons_activas:
                        margen = 5 # Grados de holgura alrededor del flujo
                        min_lat, max_lat = min(lats_activas) - margen, max(lats_activas) + margen
                        min_lon, max_lon = min(lons_activas) - margen, max(lons_activas) + margen
                    else:
                        # Valores por defecto si falla el cálculo
                        min_lat, max_lat = -56.0, -21.0
                        min_lon, max_lon = -75.0, -52.0
                    
                    fig_mapa.update_layout(
                        title_text = f"Flujo Geográfico Acumulado hasta {mes_seleccionado} (Kilos)",
                        showlegend = False,
                        height = 700,
                        margin = dict(l=0, r=0, t=40, b=0),
                        geo = dict(
                            scope = 'south america',
                            resolution = 50,
                            showframe = False,
                            showcoastlines = True,
                            coastlinecolor = '#1e7e34',  # Costa verde oscura
                            showland = True,
                            landcolor = '#000000',      # Superficie terrestre negra
                            showlakes = True,
                            showsubunits = True if not geojson_provincias else False, # Solo mostramos límites si no tenemos el GeoJSON para dibujarlos
                            #subunitcolor = '#00FF66',   # Verde brillante/eléctrico de alto contraste
                            subunitcolor = '#1e7e34', # Color de contorno provincial nativo para el Plan B
                            subunitwidth = 3,         # Grosor de la línea del límite interprovincial
                            lonaxis = dict(range=[min_lon, max_lon]), # Rango dinámico calculado
                            lataxis = dict(range=[min_lat, max_lat]), # Rango dinámico calculado
                            bgcolor = '#000000'         # Fondo general del recuadro negro
                        )
                    )

                    # --- RENDERIZADO EN STREAMLIT ---
                    st.subheader("Mapa de Rutas Activas")
                    st.plotly_chart(fig_mapa, use_container_width=True)

                    st.markdown("##### Resumen de Tramos Geográficos")
                    df_tabla_geo = df_mapa_consolidado.copy()
                    st.dataframe(
                        df_tabla_geo.sort_values(by='Kilos', ascending=False),
                        hide_index=True,
                        use_container_width=True,
                        height=580,
                        column_config={
                            "Kilos": st.column_config.NumberColumn(
                                "Kilos",
                                format="%d"  # Muestra los separadores de miles estándar del navegador
                            )
                        }
                    )

                else:
                    # ==================================================================
                    # NUEVA LÓGICA: MAPA TRIDIMENSIONAL (Torres de Kilos)
                    # ==================================================================
                    
                    fig = go.Figure()
                    
                    # Agrupamos por Tipo de Movimiento para crear capas independientes en la leyenda
                    for tipo_mov in df_flujo_mapa['TP'].unique():
                        df_tipo = df_flujo_mapa[df_flujo_mapa['TP'] == tipo_mov]
                        
                        lats_lineas = []
                        lons_lineas = []
                        textos_hover = []
                        
                        for idx, row in df_tipo.iterrows():
                            orig = row['Origen']
                            dest = row['Destino']
                            kilos = row['Kilos']
                            
                            if orig in COORDENADAS and dest in COORDENADAS:
                                c_orig = COORDENADAS[orig]
                                c_dest = COORDENADAS[dest]
                                
                                # --- CÁLCULO DE ARCOS CURVOS PARA NO SUPERPONER LÍNEAS ---
                                # Creamos 15 puntos intermedios entre el origen y el destino
                                puntos = 15
                                lats = np.linspace(c_orig['lat'], c_dest['lat'], puntos)
                                lons = np.linspace(c_orig['lon'], c_dest['lon'], puntos)
                                
                                # Agregamos una distorsión matemática en forma de parábola (arco)
                                distorsion = np.sin(np.linspace(0, np.pi, puntos)) * 0.15  # Ajustar el 0.15 para más/menos curva
                                
                                # Desviamos las coordenadas sutilmente para curvar la línea
                                lats_curvas = lats + distorsion * (c_dest['lon'] - c_orig['lon']) * 0.2
                                lons_curvas = lons - distorsion * (c_dest['lat'] - c_orig['lat']) * 0.2
                                
                                # Estructuramos los vectores para Plotly separando cada tramo con None
                                for la, lo in zip(lats_curvas, lons_curvas):
                                    lats_lineas.append(la)
                                    lons_lineas.append(lo)
                                lats_lineas.append(None)
                                lons_lineas.append(None)
                                
                                # Texto informativo para cuando pases el mouse por la ruta
                                textos_hover.append(f"Ruta: {orig} ➡️ {dest}<br>Volumen: {kilos:,.0f} Kg<br>Tipo: {tipo_mov}")

                        # Definición de colores estratégicos por tipo de flujo
                        color_linea = "#1707f0" if tipo_mov == "TRANSITO" else "#a4e905"
                        if tipo_mov == "CMV": color_linea = "#e4130c" # Naranja para ventas comerciales
                        
                        # Agregamos la capa de vectores al mapa
                        fig.add_trace(go.Scattergeo(
                            lon = lons_lineas, lat = lats_lineas,
                            mode = 'lines',
                            name = f"Flujos {tipo_mov}",
                            line = dict(width = 2, color = color_linea),
                            opacity = 0.6,
                            hoverinfo = 'text',
                            text = textos_hover
                        ))

                    # 2. Burbujas Dinámicas: Solo nodos ACTIVOS en el dataframe filtrado
                    # --- AGREGAR NODOS FIJOS COMO BURBUJAS DE VOLUMEN ---
                    # Dibujamos los puntos de las localidades para identificar los centros de masa
                    nodos_activos = set(pd.concat([df_flujo_mapa['Origen'], df_flujo_mapa['Destino']]).unique())
                    lats_nodos, lons_nodos, nombres_nodos, tamaños_nodos = [], [], [], []
                    
                    for nodo in nodos_activos:
                        nodo_upper = str(nodo).upper()
                        if nodo_upper in COORDENADAS:
                            datos = COORDENADAS[nodo_upper]
                            lats_nodos.append(datos['lat'])
                            lons_nodos.append(datos['lon'])
                            nombres_nodos.append(datos.get('display_name', nodo))
                            
                            # El tamaño responde de forma real a los kilos calculados (sin duplicar)
                            kg_real = volumen_por_localidad.get(nodo_upper, 0)
                            tamaño_dinamico = max(8, min(25, int(kg_real / 25000))) if kg_real > 0 else 8
                            tamaños_nodos.append(tamaño_dinamico)

                    if lats_nodos:
                        fig.add_trace(go.Scattergeo(
                            lon=lons_nodos, lat=lats_nodos, mode='markers',
                            name="Puntos Operativos Activos",
                            marker=dict(size=tamaños_nodos, color='#2ecc71', line=dict(width=1.5, color='black')),
                            text=nombres_nodos, hoverinfo='text'
                        ))
                        
                    fig.update_layout(
                        geo = dict(
                            scope = 'south america',
                            resolution = 50,
                            showframe = False,
                            showcoastlines = True,
                            coastlinecolor = '#1e7e34',  # Costa verde oscura
                            showland = True,
                            landcolor = '#000000',      # Superficie terrestre negra
                            showlakes = True,
                            showsubunits = True if not geojson_provincias else False, # Solo mostramos límites si no tenemos el GeoJSON para dibujarlos
                            subunitcolor = '#1e7e34', # Color de contorno provincial nativo para el Plan B
                            subunitwidth = 3,         # Grosor de la línea del límite interprovincial
                            bgcolor = '#000000',         # Fondo general del recuadro negro
                            center = dict(lat=-34.5, lon=-60.5), # Centrado automático en la zona núcleo argentina
                            projection_scale = 6
                        ),
                        margin = dict(l=0, r=0, t=30, b=0),
                        height = 600
                    )

                    # --- RENDERIZADO EN STREAMLIT ---
                    st.plotly_chart(fig, use_container_width=True)

        # ------------------------------------------------------------------
        # PANTALLA 2: EFICIENCIA DE VIAJES (Consolidación)
        # ------------------------------------------------------------------
        elif pantalla_activa == "📦 Consolidación de Viajes (Eficiencia)":
            st.subheader("🏁 Oportunidades de Consolidación de Carga (Basado en Remitos)")
            st.write("""
            **Lógica de Auditoría Avanzada:**
            1. 📑 **Agrupación por Remito:** Se calcula el peso real por unidad física (campo `NOMBRE`). Se descartan los camiones ya completos (> 25.000 Kg).
            2. 🏘️ **Destino Comercial Real:** Se cruza el remito con la hoja **'CLIENTES'** para extraer la Localidad exacta de entrega.
            3. 🛣️ **Filtro de Cercanía Geográfica (200 Km):** El sistema analiza las coordenadas y te marca explícitamente cuáles viajes parciales se dirigían a destinos cercanos dentro del mismo corredor operativo.
            """)

            dias_ventana = st.slider("Ventana de días para agrupar viajes cercanos:", min_value=1, max_value=7, value=3)
            
            # --- CARGA DINÁMICA DE LA HOJA DE CLIENTES (Puente por campo 'NOMBRE') ---
            dict_remitos_localidad = {}
            try:
                df_clientes = pd.read_excel(archivo_cargado, sheet_name="CLIENTES")
                df_clientes.columns = df_clientes.columns.str.strip()
                
                # Convertimos a string y limpiamos para asegurar el cruce perfecto de los remitos
                if 'NOMBRE' in df_clientes.columns and 'LOCALIDAD' in df_clientes.columns:
                    df_clientes['NOMBRE_Clean'] = df_clientes['NOMBRE'].astype(str).str.strip().str.upper()
                    dict_remitos_localidad = dict(zip(df_clientes['NOMBRE_Clean'], df_clientes['LOCALIDAD'].astype(str).str.strip()))
            except Exception as e:
                st.warning(f"⚠️ No se pudo procesar la hoja 'CLIENTES' o falta la columna 'LOCALIDAD'. Error: {e}")

            # Función auxiliar para calcular distancias entre puntos (Fórmula de Haversine)
            def calcular_distancia_km(ponto1, ponto2):
                if not ponto1 or not ponto2:
                    return 0
                p1_upper, p2_upper = str(ponto1).upper().strip(), str(ponto2).upper().strip()
                if p1_upper == p2_upper:
                    return 0
                if p1_upper not in COORDENADAS or p2_upper not in COORDENADAS:
                    return 9999 # Si no hay coordenadas mapeadas, asumimos distancia lejana por seguridad
                
                lat1, lon1 = COORDENADAS[p1_upper]['lat'], COORDENADAS[p1_upper]['lon']
                lat2, lon2 = COORDENADAS[p2_upper]['lat'], COORDENADAS[p2_upper]['lon']
                R = 6371.0 # Radio de la Tierra en Kms
                dlat = np.radians(lat2 - lat1)
                dlon = np.radians(lon2 - lon1)
                a = np.sin(dlat/2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon/2)**2
                c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
                return R * c

            # 1. Recuperamos tránsitos de ingreso para mapear orígenes
            ingresos_t = df_base[(df_base['TP'] == 'TRANSITO') & (df_base['Cantidad'] > 0)].copy()
            ingresos_t['Lote_Clean'] = ingresos_t['NroLote'].astype(str).str.strip().str.upper()
            transito_por_lote = dict(zip(ingresos_t['Lote_Clean'], ingresos_t['DEPOSITO']))

            viajes_procesados = []
            df_reales = df_base[df_base['TP'].isin(['TRANSITO', 'CMV'])].copy()
            
            for idx, row in df_reales.iterrows():
                tp = str(row['TP']).strip()
                dep = str(row['DEPOSITO']).strip()
                kg = float(row['Cantidad'])
                kg_abs = round(abs(kg), 2)
                lote_actual = str(row['NroLote']).strip().upper()
                remito = str(row['NOMBRE']).strip()
                remito_upper = remito.upper()
                
                if (tp == 'TRANSITO' and kg > 0) or dep == "DESCONOCIDO" or remito in ["NAN", ""]:
                    continue

                orig, dest = None, None
                if tp == 'TRANSITO':
                    orig = dep
                    # Para tránsitos buscamos primero si el remito tiene localidad en CLIENTES, sino usa el flujo por lote
                    dest = dict_remitos_localidad.get(remito_upper, transito_por_lote.get(lote_actual, "Mercadería en Tránsito"))
                elif tp == 'CMV':
                    orig = dep
                    # Buscamos la localidad en la hoja CLIENTES usando el número de remito (campo NOMBRE)
                    dest = dict_remitos_localidad.get(remito_upper, f"Zona {dep}")

                if orig and dest:
                    viajes_procesados.append({
                        'Fecha': row['Fecha'], 'Remito': remito, 'Origen_Real': orig, 'Destino_Real': dest,
                        'Kilos': kg_abs, 'TP': tp, 'Articulo': row['NomArticulo'], 'Lote': row['NroLote']
                    })

            if not viajes_procesados:
                st.info("No se registraron movimientos elegibles de TRANSITO o CMV en este archivo.")
            else:
                df_universo = pd.DataFrame(viajes_procesados)

                # Agrupamos el peso total por Remito Físico real
                df_remitos_totales = df_universo.groupby('Remito').agg(
                    Kilos_Totales_Remito=('Kilos', 'sum'),
                    Fecha_Remito=('Fecha', 'first'),
                    Origen_Remito=('Origen_Real', 'first'),
                    Destino_Remito=('Destino_Real', 'first'),
                    TP_Remito=('TP', 'first')
                ).reset_index()

                # Nos quedamos estrictamente con camiones parciales (Menores o iguales a 25.000 Kg)
                df_remitos_chicos = df_remitos_totales[df_remitos_totales['Kilos_Totales_Remito'] <= 25000].copy()

                if df_remitos_chicos.empty:
                    st.success("✅ ¡Eficiencia Máxima! Todos los remitos emitidos completaron la capacidad completa de un camión (> 25.000 Kg).")
                else:
                    df_remitos_chicos['Periodo_Viaje'] = df_remitos_chicos['Fecha_Remito'].dt.to_period(f'{dias_ventana}D').astype(str)
                    
                    # Tabla resumen ejecutiva por tramos generales
                    df_resumen_consolidacion = df_remitos_chicos.groupby(['Origen_Remito', 'Destino_Remito', 'Periodo_Viaje', 'TP_Remito']).agg(
                        Kilos_Acumulados_Tramo=('Kilos_Totales_Remito', 'sum'),
                        Cantidad_Remitos_Fragmentados=('Remito', 'count')
                    ).reset_index()

                    ineficiencias = df_resumen_consolidacion[df_resumen_consolidacion['Cantidad_Remitos_Fragmentados'] > 1].sort_values(by='Cantidad_Remitos_Fragmentados', ascending=False).reset_index(drop=True)

                    if ineficiencias.empty:
                        st.success("✅ Estructura óptima: No se detectaron remitos fraccionados duplicados para los mismos destinos exactos.")
                    else:
                        st.warning(f"⚠️ Se detectaron {len(ineficiencias)} rutas base con fragmentación de carga.")

                        ineficiencias_tabla = ineficiencias.copy()
                        ineficiencias_tabla.columns = ['Punto de Origen', 'Destino / Localidad Comercial', 'Ventana Temporal', 'Tipo de Flujo', 'Kilos Acumulados Totales', 'Cantidad Remitos Emitidos']

                        # Render de la tabla superior interactiva
                        seleccion = st.dataframe(
                            ineficiencias_tabla.style.format({"Kilos Acumulados Totales": "{:,.0f}"}),
                            use_container_width=True, hide_index=True,
                            selection_mode="single-row", on_select="rerun"
                        )

                        filas_seleccionadas = seleccion.get("selection", {}).get("rows", [])

                        # --- APERTURA TÉCNICA CON ANÁLISIS DE RADIO DE 200 KMS ---
                        if filas_seleccionadas:
                            indice_fila = filas_seleccionadas[0]
                            fila_activa = ineficiencias.iloc[indice_fila]

                            st.markdown("---")
                            st.subheader("🔍 Apertura Técnica de Remitos en este Tramo:")
                            
                            # Traemos todos los remitos parciales emitidos en la misma ventana de días
                            remitos_ventana = df_remitos_chicos[df_remitos_chicos['Periodo_Viaje'] == fila_activa['Periodo_Viaje']].copy()
                            
                            remitos_validados = []
                            for idx_r, remito_row in remitos_ventana.iterrows():
                                # Calculamos la distancia real usando la fórmula de Haversine entre las localidades
                                distancia = calcular_distancia_km(fila_activa['Destino_Remito'], remito_row['Destino_Remito'])
                                
                                # Criterio geográfico: Mismo origen y destinos a menos de 200 Kms de distancia
                                if remito_row['Origen_Remito'] == fila_activa['Origen_Remito'] and distancia <= 200:
                                    if distancia == 0:
                                        dictamen = "⚠️ Duplicado (Mismo Destino Exacto)"
                                        dist_str = "0.0 Km"
                                    else:
                                        dictamen = "🚨 CONSOLIDABLE (Destino Cercano < 200Km)"
                                        dist_str = f"{distancia:.1f} Km"

                                    remitos_validados.append({
                                        'Remito': remito_row['Remito'],
                                        'Localidad_Destino': remito_row['Destino_Remito'],
                                        'Distancia_Ref': dist_str,
                                        'Accion': dictamen
                                    })
                            
                            df_geo_valida = pd.DataFrame(remitos_validados)

                            if df_geo_valida.empty:
                                st.info("No se hallaron desvíos o remitos combinables para este tramo.")
                            else:
                                # Cruzamos el filtro geográfico con los renglones físicos de los artículos/lotes
                                df_detalle_universo = df_universo[df_universo['Remito'].isin(df_geo_valida['Remito'])].copy()
                                df_final_render = df_detalle_universo.merge(df_geo_valida, on='Remito', how='left')
                                
                                df_final_render['Fecha'] = df_final_render['Fecha'].dt.strftime('%Y-%m-%d')
                                df_final_render_tabla = df_final_render[['Fecha', 'Remito', 'Lote', 'Articulo', 'Kilos', 'Localidad_Destino', 'Distancia_Ref', 'Accion']].sort_values(by=['Accion', 'Fecha', 'Remito'])
                                
                                df_final_render_tabla.columns = [
                                    '📅 Fecha Despacho', '📄 Nro. Remito (NOMBRE)', '🆔 Nro. Lote', 
                                    '🌱 Producto / Variedad', '⚖️ Kilos Renglón', 
                                    '📍 Localidad Real Destino', '🛣️ Distancia al Destino Base', '📢 Dictamen Operativo'
                                ]

                                # Formato de color para identificar los desvíos rápidamente
                                def colorear_dictamen(val):
                                    if 'Cercano' in str(val):
                                        return 'background-color: rgba(46, 204, 113, 0.2)' # Verde suave para rutas combinables
                                    return 'background-color: rgba(241, 196, 15, 0.2)' # Amarillo para el mismo destino exacto

                                st.dataframe(
                                    df_final_render_tabla.style.format({"⚖️ Kilos Renglón": "{:,.0f}"}).map(colorear_dictamen, subset=['📢 Dictamen Operativo']),
                                    use_container_width=True, hide_index=True
                                )
                        else:
                            st.info("💡 Hacé clic en la casilla izquierda de cualquier fila superior para abrir la auditoría geográfica por localidades y distancias.")
        # ------------------------------------------------------------------
        # PANTALLA 3: ANÁLISIS DE HUBS (Ubicación de depósitos)
        # ------------------------------------------------------------------
        elif pantalla_activa == "🏭 Análisis de Hubs (Nuevos Depósitos)":
            st.subheader("📍 Análisis de Densidad de Entregas para Apertura de Hubs")
            st.write("Análisis de concentración de Kilos despachados a zonas comerciales para justificar la apertura estratégica de depósitos regionales.")

            # Filtramos los despachos comerciales (CMV)
            df_hubs = df_base[df_base['TP'] == 'CMV'].copy()
            df_hubs['Kilos_Abs'] = df_hubs['Cantidad'].abs()
            
            # Agrupamos por la columna física 'DEPOSITO' que guarda la sucursal/zona destino de la venta
            analisis_zonas = df_hubs.groupby('DEPOSITO').agg(
                Kilos_Despachados=('Kilos_Abs', 'sum'),
                Clientes_Atendidos=('NOMBRE', 'nunique') if 'NOMBRE' in df_hubs.columns else ('DEPOSITO', 'count'),
                Frecuencia_Envios=('Fecha', 'count')
            ).reset_index().sort_values(by='Kilos_Despachados', ascending=False)
            
            if analisis_zonas.empty:
                st.info("No se registran movimientos de venta (CMV) en el archivo actual para analizar zonas de distribución.")
            else:
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.write("### 📊 Ranking de Concentración de Demanda Comercial")
                    analisis_zonas_tabla = analisis_zonas.copy()
                    analisis_zonas_tabla.columns = ['Zona / Destino Comercial', 'Kilos Totales Recibidos', 'Clientes Únicos', 'Cantidad de Entregas']
                    st.dataframe(analisis_zonas_tabla, use_container_width=True, hide_index=True)
                with col2:
                    st.write("### 🧠 Sugerencia Estratégica")
                    top_zona = analisis_zonas.iloc[0]
                    st.info(f"""
                    **Zona Crítica Detectada:**
                    La zona de **{top_zona['DEPOSITO']}** absorbió un volumen total de **{top_zona['Kilos_Despachados']:,.0f} Kg** distribuidos en **{top_zona['Frecuencia_Envios']} despachos**. 
                    
                    💡 *Propuesta Financiera:* Evaluar la contratación de un depósito tercerizado en esta área geográfica para consolidar fletes largos desde casa matriz en camiones completos y coordinar la entrega de 'última milla' localmente.
                    """)

    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")
                
else:
    st.info("💡 Esperando archivo de movimientos para mapear ineficiencias...")
