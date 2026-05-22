import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
import requests

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
                "Proveedor Ext.":  {"lat": -34.5936, "lon": -58.3715}, # Puerto Buenos Aires
                "Cliente (Venta)": {"lat": -32.9468, "lon": -60.6393}, # Rosario / Zona Núcleo
                "Mercadería en Tránsito": {"lat": -34.3000, "lon": -59.5000}, # Punto intermedio ruta
                "Ajustes de Inventario": {"lat": -33.8923, "lon": -60.5735},  # Base Pergamino
                "Linea Proceso (Virt.)": {"lat": -33.8923, "lon": -60.5735},
                "DESCONOCIDO":    {"lat": -34.6037, "lon": -58.3816},
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

        # --------------------- FILTROS ---
        st.sidebar.header("Filtros Operativos")
        
        # Filtro por Familia primero, para acotar
        familias = sorted(df_base['FAMILIA'].dropna().astype(str).unique())
        familia_sel = st.sidebar.selectbox("1. Filtrar por Familia:", ["TODAS"] + familias)
        df_f = df_base if familia_sel == "TODAS" else df_base[df_base['FAMILIA'].astype(str) == familia_sel]
        
        # Filtro por Artículo
        articulos = sorted(df_f['NomArticulo'].dropna().astype(str).unique())
        articulo_sel = st.sidebar.selectbox("2. Selecciona el Producto:", articulos)
        df_filtrado = df_f[df_f['NomArticulo'] == articulo_sel].copy()
        df_filtrado['Kilos'] = df_filtrado['Cantidad'].abs()
        df_articulo = df_filtrado.copy()

        # COMANDO: Control de apertura geográfica solicitado
        st.sidebar.markdown("---")
        st.sidebar.header("⚙️ Configuración del Mapa")
        apertura_cliente_sel = st.sidebar.radio("Apertura Cliente:", ["NO", "SI"], index=0, help="Determina si el mapa proyecta los clientes individualmente o consolidados.")
        apertura_cliente = (apertura_cliente_sel == "SI")        

        # ----------------------- LÓGICA DE CONTROL DEL TIEMPO (REPRODUCTOR) ---
        st.sidebar.markdown("---")
        st.sidebar.header("⏱️ Control del Tiempo")
        meses_disponibles = sorted(df_articulo['MES'].dropna().unique())

        if len(meses_disponibles) > 0:
            # Inicializamos en el último índice (el final de la lista)
            ultimo_indice = len(meses_disponibles) - 1

            # Inicializamos una variable de estado en Streamlit para controlar el reproductor
            if "mes_index" not in st.session_state:
                st.session_state.mes_index = ultimo_indice

            # Protección extra: si cambiás de artículo y tiene menos meses que el anterior,
            # forzamos el índice a reajustarse al nuevo final para evitar desbordamientos.
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

            # El control deslizante ahora toma por defecto la posición actual guardada (que arranca al final)
            mes_seleccionado = st.sidebar.select_slider(
                "Hasta el mes:", 
                options=meses_disponibles,
                value=meses_disponibles[st.session_state.mes_index],
                key="slider_tiempo"
            )

            # Sincronizamos el estado si el usuario mueve el slider manualmente
            st.session_state.mes_index = meses_disponibles.index(mes_seleccionado)
            df_filtrado = df_articulo[df_articulo['MES'] <= mes_seleccionado].copy()
        else:
            df_filtrado = df_articulo
            st.warning("No se encontraron datos en la columna MES para este artículo.")

        # --- CORRECCIÓN CRÍTICA: EXTRAER Y MOSTRAR STOCK INICIAL ESTÁTICO ---
        #st.subheader("📋 Foto de Inventario Inicial (No es movimiento)")
        
        # Filtramos los registros que sean INI en todo el historial cargado para este artículo
        #df_ini = df_articulo[df_articulo['TP'] == 'INI']
        
        #if not df_ini.empty:
            # Agrupamos por depósito para saber cuánto había en cada lugar al inicio de todo
        #    stock_inicial_por_dep = df_ini.groupby('DEPOSITO')['Cantidad'].sum()
            
            # Dibujamos tarjetas métricas lindas en columnas horizontales
        #   cols_metricas = st.columns(len(stock_inicial_por_dep))
        #    for idx, (deposito_nombre, kilos_iniciales) in enumerate(stock_inicial_por_dep.items()):
        #        with cols_metricas[idx]:
        #            st.metric(label=f"STK Inicial en {deposito_nombre}", value=f"{kilos_iniciales:,.0f} Kg")
        #else:
        #    st.info("No se registraron registros de Stock Inicial (INI) para este producto.")
        #st.markdown("---")

        # ==================================================================
        # LÓGICA 1: PREPARACIÓN EXCLUSIVA PARA EL SANKEY Y EL MAPA DE FLUJO
        # ==================================================================

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
            
            if tp in ['FOB']:
                orig, dest = "Proveedor Ext.", dep
            elif tp == 'CPRA':
                orig, dest = "Proveedor Local", dep
            elif tp == 'INI':
                orig, dest = "Stock Inicial (Virt.)", dep
            elif tp == 'CMV':
                orig, dest = dep, "Cliente (Venta)"
            elif tp == 'Baja_PRODUCC':
                orig, dest = dep, "Baja/Merma Proceso"
            elif tp == 'PRODUCC':
                if kg > 0:
                    orig, dest = "Linea Proceso (Virt.)", dep
                else:
                    orig, dest = dep, "Linea Proceso (Virt.)"
            elif tp == 'TRANSITO':
                if kg < 0:
                    orig, dest = dep, "Mercadería en Tránsito"
                else:
                    orig, dest = "Mercadería en Tránsito", dep
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

        for idx, row in df_filtrado.iterrows():
            tp = row['TP']
            dep = row['DEPOSITO'].upper()

            #if tp in ["SIN_TP", "FIN", "INI"] or dep in ["#N/A", "N/A", "NAN"]:
            if tp in ["SIN_TP", "FIN"] or dep in ["#N/A", "N/A", "NAN"]:
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
                orig, dest = (dep, "MERCADERÍA EN TRÁNSITO") if kg < 0 else ("MERCADERÍA EN TRÁNSITO", dep)
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
        
            st.subheader("Detalle de Movimientos")
            df_tabla = df_filtrado[['Fecha', 'DEPOSITO', 'NOMBRE', 'TP', 'Kilos']].copy()
            df_tabla['Fecha'] = df_tabla['Fecha'].dt.strftime('%Y-%m-%d')
            st.dataframe(df_tabla.sort_values(by='Fecha'), use_container_width=True, hide_index=True, height=520)

            # --- SECCIÓN ENMARCADA INFERIOR: MAPA GEOGRÁFICO ---
            st.markdown("---")
        
            st.subheader("Análisis de Concentración")
            st.write("Volumen total manejado por tramo:")
            df_tabla_ver = df_agrupado_sankey.copy()
            df_tabla_ver['Kilos'] = df_tabla_ver['Kilos'].map('{:,.2f}'.format)
            st.dataframe(df_tabla_ver.sort_values(by='Kilos', ascending=False), hide_index=True, use_container_width=True)

            st.markdown("---")

            # ----- MAPA GEOGRÁFICO DE DEPÓSITOS (OPCIONAL) -----
            st.subheader("🗺️ Representación Geográfica de Entregas")
            
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
                o_name = row['Origen']
                d_name = row['Destino']
                tipo_p = row['TP']

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
            df_tabla_geo['Kilos'] = df_tabla_geo['Kilos'].map('{:,.0f}'.format)
            st.dataframe(df_tabla_geo.sort_values(by='Kilos', ascending=False), hide_index=True, use_container_width=True, height=580)

    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")
                
else:
    st.info("💡 Esperando archivo de movimientos para mapear ineficiencias...")
