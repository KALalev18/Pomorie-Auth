export interface LatLng {
  lat: number;
  lng: number;
}

export interface MapViewProps {
  onInsideClick: (latLng: LatLng) => void;
  onOutsideClick: () => void;
  markerPosition: LatLng | null;
}
