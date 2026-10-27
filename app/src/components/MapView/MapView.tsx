import { useEffect, useRef } from 'react';
import maplibregl, { type StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { boundaryContains, loadBoundary, outsideMask } from './boundary';
import type { MapViewProps } from './MapView.types';

// Geographic centre of the Pomorie municipality (not the town)
const POMORIE_CENTER: [number, number] = [27.545, 42.61];

// Standard OSM raster tiles: free, no API key, attribution required.
const OSM_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
};

export default function MapView({ onInsideClick, onOutsideClick, markerPosition }: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);

  // Keep the latest callbacks without re-creating the map when they change.
  const callbacks = useRef({ onInsideClick, onOutsideClick });
  callbacks.current = { onInsideClick, onOutsideClick };

  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_STYLE,
      center: POMORIE_CENTER,
      zoom: 10.5,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
    mapRef.current = map;

    const boundaryPromise = loadBoundary();

    map.on('load', async () => {
      const boundary = await boundaryPromise;
      map.addSource('outside', { type: 'geojson', data: outsideMask(boundary.features[0]) });
      map.addSource('boundary', { type: 'geojson', data: boundary });
      map.addLayer({
        id: 'outside-fill',
        type: 'fill',
        source: 'outside',
        paint: { 'fill-color': '#ef4444', 'fill-opacity': 0.18 },
      });
      map.addLayer({
        id: 'boundary-line',
        type: 'line',
        source: 'boundary',
        paint: { 'line-color': '#ef4444', 'line-width': 2.5, 'line-opacity': 0.9 },
      });
    });

    map.on('click', async (e) => {
      const boundary = await boundaryPromise;
      const latLng = { lat: e.lngLat.lat, lng: e.lngLat.lng };
      if (boundaryContains(boundary.features[0], latLng)) {
        callbacks.current.onInsideClick(latLng);
      } else {
        callbacks.current.onOutsideClick();
      }
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    markerRef.current?.remove();
    markerRef.current = null;
    if (markerPosition && mapRef.current) {
      markerRef.current = new maplibregl.Marker({ color: '#0ea5e9' })
        .setLngLat([markerPosition.lng, markerPosition.lat])
        .addTo(mapRef.current);
    }
  }, [markerPosition]);

  return <div ref={containerRef} className="h-full w-full" aria-label="Карта на Община Поморие" />;
}
