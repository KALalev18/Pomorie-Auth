import { useCallback } from 'react';
import {
  Map,
  AdvancedMarker,
  Polygon,
  useMapsLibrary,
  type MapMouseEvent,
} from '@vis.gl/react-google-maps';
import { getMunicipalityPolygonPath } from './pomorieBounds';
import type { MapViewProps } from './MapView.types';

// Geographic centre of the Pomorie municipality (not the city)
const POMORIE_CENTER = { lat: 42.610, lng: 27.545 };
const MAP_ID = import.meta.env.VITE_GOOGLE_MAPS_MAP_ID as string | undefined;

// Large CCW outer ring — covers the visible region; municipality path (CW) punches a transparent hole
const OUTER_RING: Array<{ lat: number; lng: number }> = [
  { lat: 44.0, lng: 26.0 },
  { lat: 41.0, lng: 26.0 },
  { lat: 41.0, lng: 29.0 },
  { lat: 44.0, lng: 29.0 },
];

export default function MapView({ onInsideClick, onOutsideClick, markerPosition }: MapViewProps) {
  const geometryLib = useMapsLibrary('geometry');

  const handleMapClick = useCallback(
    (e: MapMouseEvent) => {
      if (!e.detail.latLng || !geometryLib) return;
      const { lat, lng } = e.detail.latLng;

      const polygonPath = getMunicipalityPolygonPath();
      const polygon = new google.maps.Polygon({ paths: polygonPath });
      const gmLatLng = new google.maps.LatLng(lat, lng);
      const isInside = geometryLib.poly.containsLocation(gmLatLng, polygon);

      const latLng = { lat, lng };
      isInside ? onInsideClick(latLng) : onOutsideClick();
    },
    [geometryLib, onInsideClick, onOutsideClick],
  );

  return (
    <Map
      mapId={MAP_ID}
      defaultCenter={POMORIE_CENTER}
      defaultZoom={12}
      gestureHandling="greedy"
      disableDefaultUI={false}
      controlSize={28}
      onClick={handleMapClick}
      style={{ width: '100%', height: '100%' }}
      className="h-full w-full"
    >
      {/* ── red overlay outside the municipality boundary ── */}
      <Polygon
        paths={[OUTER_RING, getMunicipalityPolygonPath()]}
        strokeColor="#ef4444"
        strokeOpacity={0.9}
        strokeWeight={2.5}
        fillColor="#ef4444"
        fillOpacity={0.18}
        clickable={false}
        zIndex={1}
      />

      {/* ── bright border line on the municipality edge ── */}
      <Polygon
        paths={getMunicipalityPolygonPath()}
        strokeColor="#ffffff"
        strokeOpacity={0.55}
        strokeWeight={1}
        fillOpacity={0}
        clickable={false}
        zIndex={2}
      />

      {markerPosition && (
        <AdvancedMarker position={markerPosition} title="Избрано местоположение" />
      )}
    </Map>
  );
}

