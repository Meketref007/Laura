import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Switch,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import API from '../api';
import { darkTheme, lightTheme } from '../theme';

const APP_VERSION = '1.0.0';

const ThemeContext = React.createContext();

export function ThemeProvider({ children, initialTheme }) {
  const [isDark, setIsDark] = useState(initialTheme !== false);
  const theme = isDark ? darkTheme : lightTheme;

  const toggleTheme = useCallback(() => {
    setIsDark((prev) => !prev);
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, isDark, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = React.useContext(ThemeContext);
  if (!ctx) return darkTheme;
  return ctx.theme;
}

export function useThemeToggle() {
  const ctx = React.useContext(ThemeContext);
  if (!ctx) return { isDark: true, toggleTheme: () => {} };
  return { isDark: ctx.isDark, toggleTheme: ctx.toggleTheme };
}

export default function SettingsScreen() {
  const { theme, isDark, toggleTheme } = React.useContext(ThemeContext);
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [testing, setTesting] = useState(false);

  useFocusEffect(
    useCallback(() => {
      (async () => {
        const config = await API.getConfig();
        setBaseUrl(config.baseUrl);
        setApiKey(config.apiKey);
      })();
    }, [])
  );

  const saveUrl = async () => {
    const trimmed = baseUrl.trim();
    if (!trimmed) {
      Alert.alert('Error', 'Please enter a valid URL');
      return;
    }
    await API.setBaseUrl(trimmed);
    Alert.alert('Saved', 'API URL updated');
  };

  const saveKey = async () => {
    await API.setApiKey(apiKey.trim());
    Alert.alert('Saved', 'API Key updated');
  };

  const testConnection = async () => {
    setTesting(true);
    const ok = await API.testConnection();
    setTesting(false);
    if (ok) {
      Alert.alert('Success', 'Connected to Laura API successfully');
    } else {
      Alert.alert('Failed', 'Could not connect to Laura API. Check the URL and key.');
    }
  };

  return (
    <ScrollView
      style={[styles.container, { backgroundColor: theme.background }]}
      contentContainerStyle={styles.content}
    >
      <Text style={[styles.sectionTitle, { color: theme.text }]}>API Configuration</Text>

      <Text style={[styles.label, { color: theme.textSecondary }]}>Base URL</Text>
      <TextInput
        style={[
          styles.input,
          {
            backgroundColor: theme.surface,
            color: theme.text,
            borderColor: theme.border,
          },
        ]}
        value={baseUrl}
        onChangeText={setBaseUrl}
        placeholder="http://192.168.0.1:8888"
        placeholderTextColor={theme.textSecondary}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
      />
      <TouchableOpacity
        style={[styles.button, { backgroundColor: theme.accent }]}
        onPress={saveUrl}
      >
        <Text style={styles.buttonText}>Save URL</Text>
      </TouchableOpacity>

      <Text style={[styles.label, { color: theme.textSecondary, marginTop: 20 }]}>API Key</Text>
      <TextInput
        style={[
          styles.input,
          {
            backgroundColor: theme.surface,
            color: theme.text,
            borderColor: theme.border,
          },
        ]}
        value={apiKey}
        onChangeText={setApiKey}
        placeholder="Enter your API key"
        placeholderTextColor={theme.textSecondary}
        autoCapitalize="none"
        autoCorrect={false}
        secureTextEntry
      />
      <TouchableOpacity
        style={[styles.button, { backgroundColor: theme.accent }]}
        onPress={saveKey}
      >
        <Text style={styles.buttonText}>Save Key</Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={[styles.button, styles.testButton, { borderColor: theme.accent }]}
        onPress={testConnection}
        disabled={testing}
      >
        {testing ? (
          <ActivityIndicator color={theme.accent} />
        ) : (
          <Text style={[styles.buttonTextOutline, { color: theme.accent }]}>
            Test Connection
          </Text>
        )}
      </TouchableOpacity>

      <View style={[styles.divider, { backgroundColor: theme.border }]} />

      <View style={styles.themeRow}>
        <View>
          <Text style={[styles.themeLabel, { color: theme.text }]}>Dark Mode</Text>
          <Text style={[styles.themeHint, { color: theme.textSecondary }]}>
            {isDark ? 'Dark theme active' : 'Light theme active'}
          </Text>
        </View>
        <Switch
          value={isDark}
          onValueChange={toggleTheme}
          trackColor={{ false: theme.border, true: theme.accent }}
          thumbColor={isDark ? '#e2e8f0' : '#94a3b8'}
        />
      </View>

      <View style={[styles.divider, { backgroundColor: theme.border }]} />

      <View style={styles.versionRow}>
        <Text style={[styles.versionLabel, { color: theme.textSecondary }]}>App Version</Text>
        <Text style={[styles.versionValue, { color: theme.text }]}>{APP_VERSION}</Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  content: { padding: 20, paddingBottom: 40 },
  sectionTitle: { fontSize: 20, fontWeight: '700', marginBottom: 16 },
  label: { fontSize: 13, fontWeight: '600', marginBottom: 6 },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
  },
  button: {
    marginTop: 8,
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: 'center',
  },
  buttonText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  testButton: {
    marginTop: 16,
    backgroundColor: 'transparent',
    borderWidth: 1.5,
  },
  buttonTextOutline: { fontSize: 15, fontWeight: '600' },
  divider: { height: 1, marginVertical: 24 },
  themeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  themeLabel: { fontSize: 16, fontWeight: '600' },
  themeHint: { fontSize: 13, marginTop: 2 },
  versionRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  versionLabel: { fontSize: 14 },
  versionValue: { fontSize: 14, fontWeight: '600' },
});
